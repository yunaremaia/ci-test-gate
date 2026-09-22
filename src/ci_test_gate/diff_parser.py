"""Parse unified diff output into structured file changes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileChange:
    path: str
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)
    hunks: list[str] = field(default_factory=list)
    is_new: bool = False
    is_deleted: bool = False
    is_binary: bool = False

    @property
    def extension(self) -> str:
        return Path(self.path).suffix

    @property
    def is_test_file(self) -> bool:
        name = Path(self.path).name
        return (
            name.startswith("test_")
            or name.endswith("_test.py")
            or name.endswith(".test.ts")
            or name.endswith(".test.js")
            or name.endswith(".spec.ts")
            or name.endswith(".spec.js")
            or "_test.go" in name
            or "test" in self.path.split("/")
        )


class DiffParser:
    """Parse git diff output into structured FileChange objects."""

    FILE_HEADER_RE = re.compile(r"^diff --git (?:a/)?(.+) (?:b/)?(.+)$")
    NEW_FILE_RE = re.compile(r"^new file mode")
    DELETED_FILE_RE = re.compile(r"^deleted file mode")
    HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    def parse(self, diff_text: str) -> list[FileChange]:
        """Parse a unified diff string into a list of FileChange objects."""
        changes: list[FileChange] = []
        current_change: FileChange | None = None
        current_hunk: list[str] = []

        for raw_line in diff_text.splitlines():
            line = raw_line.strip()

            file_match = self.FILE_HEADER_RE.match(line)
            if file_match:
                if current_change is not None:
                    if current_hunk:
                        current_change.hunks.append("\n".join(current_hunk))
                    changes.append(current_change)
                current_change = FileChange(path=file_match.group(2))
                current_hunk = []
                continue

            if current_change is None:
                continue

            if line == "\\ No newline at end of file":
                continue

            if (line.startswith("Binary files ") and line.endswith(" differ")) or (
                line == "GIT binary patch"
            ):
                current_change.is_binary = True
                continue

            if current_change.is_binary:
                continue

            if self.NEW_FILE_RE.match(line):
                current_change.is_new = True
                continue

            if self.DELETED_FILE_RE.match(line):
                current_change.is_deleted = True
                continue

            hunk_match = self.HUNK_HEADER_RE.match(line)
            if hunk_match:
                if current_hunk:
                    current_change.hunks.append("\n".join(current_hunk))
                current_hunk = []
                continue

            if line.startswith("+") and not line.startswith("+++"):
                current_change.added_lines.append(line[1:])
                current_hunk.append(raw_line)
            elif line.startswith("-") and not line.startswith("---"):
                current_change.removed_lines.append(line[1:])
                current_hunk.append(raw_line)
            elif line.startswith(" "):
                current_hunk.append(raw_line)

        if current_change is not None:
            if current_hunk:
                current_change.hunks.append("\n".join(current_hunk))
            changes.append(current_change)

        return changes

    def get_changed_extensions(self, changes: list[FileChange]) -> set[str]:
        """Get unique file extensions from changes."""
        return {c.extension for c in changes if c.extension}

    def get_changed_paths(self, changes: list[FileChange]) -> list[str]:
        """Get list of changed file paths."""
        return [c.path for c in changes]

    def filter_by_extension(self, changes: list[FileChange], ext: str) -> list[FileChange]:
        """Filter changes by file extension."""
        return [c for c in changes if c.extension == ext]

    def get_non_test_changes(self, changes: list[FileChange]) -> list[FileChange]:
        """Get non-binary changes that are not test files."""
        return [c for c in changes if not c.is_test_file and not c.is_binary]

    def get_test_changes(self, changes: list[FileChange]) -> list[FileChange]:
        """Get non-binary changes that are test files."""
        return [c for c in changes if c.is_test_file and not c.is_binary]
