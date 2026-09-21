"""Build rich context from diff changes for LLM classification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .diff_parser import FileChange


@dataclass
class ChangeContext:
    """Structured context about a code change."""
    changed_files: list[FileChange]
    imports_added: dict[str, list[str]] = field(default_factory=dict)
    imports_removed: dict[str, list[str]] = field(default_factory=dict)
    functions_changed: dict[str, list[str]] = field(default_factory=dict)
    test_files_present: list[str] = field(default_factory=list)
    test_runners_detected: list[str] = field(default_factory=list)
    estimated_scope: str = "small"  # small, medium, large

    def to_prompt_context(self) -> str:
        """Generate a text summary for LLM prompt."""
        lines = []
        lines.append(f"Scope: {self.estimated_scope}")
        lines.append(f"Changed files: {len(self.changed_files)}")
        lines.append(f"Test files present: {len(self.test_files_present)}")
        lines.append(f"Test runners: {', '.join(self.test_runners_detected) or 'none detected'}")
        
        if self.imports_added:
            lines.append("Imports added:")
            for path, imports in self.imports_added.items():
                lines.append(f"  {path}: {', '.join(imports)}")
        
        if self.imports_removed:
            lines.append("Imports removed:")
            for path, imports in self.imports_removed.items():
                lines.append(f"  {path}: {', '.join(imports)}")
        
        if self.functions_changed:
            lines.append("Functions changed:")
            for path, funcs in self.functions_changed.items():
                lines.append(f"  {path}: {', '.join(funcs)}")
        
        return "\n".join(lines)


class ContextBuilder:
    """Analyze diff to build context for test selection."""

    IMPORT_PATTERNS = {
        ".py": [
            re.compile(r"^from\s+([\w.]+)\s+import\s+(.+)$"),
            re.compile(r"^import\s+([\w.]+)"),
        ],
        ".ts": [
            re.compile(r"^import\s+.+\s+from\s+['\"](.+)['\"]"),
            re.compile(r"^import\s+['\"](.+)['\"]"),
        ],
        ".js": [
            re.compile(r"^import\s+.+\s+from\s+['\"](.+)['\"]"),
            re.compile(r"^const\s+.+\s+require\s*\(\s*['\"](.+)['\"]\s*\)"),
        ],
        ".go": [
            re.compile(r'^\s*import\s+\(\s*"([^"]+)"'),
            re.compile(r'^\s*import\s+"([^"]+)"'),
        ],
        ".rs": [
            re.compile(r"^use\s+([\w:]+)"),
        ],
    }

    FUNCTION_PATTERNS = {
        ".py": re.compile(r"^def\s+(\w+)\s*\("),
        ".ts": re.compile(r"^(export\s+)?(async\s+)?function\s+(\w+)\s*\("),
        ".js": re.compile(r"^(export\s+)?(async\s+)?function\s+(\w+)\s*\("),
        ".go": re.compile(r"^func\s+(\w+)\s*\("),
        ".rs": re.compile(r"^(pub\s+)?fn\s+(\w+)\s*\("),
    }

    TEST_RUNNER_FILES = {
        "pytest.ini", "setup.cfg", "pyproject.toml", "tox.ini",
        "jest.config.js", "jest.config.ts", "vitest.config.js",
        "package.json", "go.mod", "Cargo.toml",
    }

    def build(self, changes: list[FileChange]) -> ChangeContext:
        """Build context from a list of file changes."""
        context = ChangeContext(changed_files=changes)
        context.test_files_present = [c.path for c in changes if c.is_test_file]
        context.test_runners_detected = self._detect_test_runners(changes)
        
        # Estimate scope
        total_lines = sum(len(c.added_lines) + len(c.removed_lines) for c in changes)
        if total_lines > 500 or len(changes) > 20:
            context.estimated_scope = "large"
        elif total_lines > 100 or len(changes) > 5:
            context.estimated_scope = "medium"

        for change in changes:
            ext = change.extension
            if ext in self.IMPORT_PATTERNS:
                self._extract_imports(change, context, ext)
            if ext in self.FUNCTION_PATTERNS:
                self._extract_functions(change, context, ext)

        return context

    def _detect_test_runners(self, changes: list[FileChange]) -> list[str]:
        """Detect which test frameworks are in use."""
        runners = set()
        for change in changes:
            filename = Path(change.path).name
            if filename in self.TEST_RUNNER_FILES:
                if filename == "pyproject.toml":
                    content = "\n".join(change.added_lines)
                    if "pytest" in content:
                        runners.add("pytest")
                elif filename == "package.json":
                    content = "\n".join(change.added_lines)
                    if "jest" in content:
                        runners.add("jest")
                    if "vitest" in content:
                        runners.add("vitest")
                    if "mocha" in content:
                        runners.add("mocha")
                elif filename == "Cargo.toml":
                    runners.add("cargo test")
                elif filename == "go.mod":
                    runners.add("go test")
                elif filename in ("pytest.ini", "setup.cfg", "tox.ini"):
                    runners.add("pytest")
                elif filename.startswith("jest.config"):
                    runners.add("jest")
        return list(runners)

    def _extract_imports(self, change: FileChange, context: ChangeContext, ext: str) -> None:
        """Extract imports from added/removed lines."""
        for line in change.added_lines:
            for pattern in self.IMPORT_PATTERNS[ext]:
                match = pattern.match(line.strip())
                if match:
                    context.imports_added.setdefault(change.path, []).append(match.group(1))
                    break
        for line in change.removed_lines:
            for pattern in self.IMPORT_PATTERNS[ext]:
                match = pattern.match(line.strip())
                if match:
                    context.imports_removed.setdefault(change.path, []).append(match.group(1))
                    break

    def _extract_functions(self, change: FileChange, context: ChangeContext, ext: str) -> None:
        """Extract function definitions from added/removed lines."""
        for line in change.added_lines:
            match = self.FUNCTION_PATTERNS[ext].match(line.strip())
            if match:
                func_name = match.group(3) if ext in (".ts", ".js") else match.group(1)
                if not func_name:
                    func_name = match.group(0)
                context.functions_changed.setdefault(change.path, []).append(f"+{func_name}")
        for line in change.removed_lines:
            match = self.FUNCTION_PATTERNS[ext].match(line.strip())
            if match:
                func_name = match.group(3) if ext in (".ts", ".js") else match.group(1)
                if not func_name:
                    func_name = match.group(0)
                context.functions_changed.setdefault(change.path, []).append(f"-{func_name}")
