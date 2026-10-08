"""SARIF 2.1.0 output for ci-test-gate — GitHub Code Scanning integration."""

from __future__ import annotations

import json
from typing import Any

# SARIF rule IDs
RULE_MISSING_REQUIRED_TEST = "ci-test-gate/missing-required-test"
RULE_UNTESTED_CHANGED_FILE = "ci-test-gate/untested-changed-file"

RULES = [
    {
        "id": RULE_MISSING_REQUIRED_TEST,
        "name": "MissingRequiredTest",
        "shortDescription": {"text": "Required test not executed"},
        "fullDescription": {
            "text": "A source file changed but its required test suite was not selected to run."
        },
        "helpUri": "https://github.com/yunaremaia/ci-test-gate",
        "properties": {
            "category": "testing",
            "security-severity": "7.0",
        },
    },
    {
        "id": RULE_UNTESTED_CHANGED_FILE,
        "name": "UntestedChangedFile",
        "shortDescription": {"text": "Changed source file has no test coverage"},
        "fullDescription": {
            "text": "A source file was changed in this commit but has no corresponding test suite selected."
        },
        "helpUri": "https://github.com/yunaremaia/ci-test-gate",
        "properties": {
            "category": "testing",
            "security-severity": "4.0",
        },
    },
]


def _is_source_tested(source_path: str, test_paths: set[str]) -> bool:
    """Check if a source file is covered by any test path.

    Mirrors the heuristic classifier's matching logic: a test path matches a
    source path when the test's base name (after stripping ``test_`` prefix,
    ``_test.`` suffix, and ``tests/`` dir) is a substring of the source path.
    """
    for tp in test_paths:
        tp_base = tp.replace("test_", "").replace("_test.", ".").replace("tests/", "")
        if tp_base in source_path or source_path in tp:
            return True
    return False


def recommendation_to_sarif(
    required: list[str],
    recommended: list[str],
    all_changed_files: list[str] | None = None,
    tool_version: str = "0.1.0",
) -> dict[str, Any]:
    """Convert test selection results to a SARIF 2.1.0 document.

    Args:
        required: List of required test paths.
        recommended: List of recommended test paths.
        all_changed_files: Optional list of all changed source files.
            Used to detect files with no test coverage at all.
        tool_version: Tool version string for the SARIF document.
    """
    results: list[dict[str, Any]] = []

    # Flag required tests that might be missing (empty required with changes)
    tested_paths = set(required) | set(recommended)

    # Untested changed files (no recommendation at all)
    if all_changed_files:
        for file_path in all_changed_files:
            if not _is_source_tested(file_path, tested_paths):
                results.append({
                    "ruleId": RULE_UNTESTED_CHANGED_FILE,
                    "level": "warning",
                    "message": {
                        "text": f"No test suite selected for changed file: {file_path}",
                    },
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {
                                    "uri": file_path,
                                },
                            },
                        },
                    ],
                })

    return {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "ci-test-gate",
                        "version": tool_version,
                        "informationUri": "https://github.com/yunaremaia/ci-test-gate",
                        "rules": RULES,
                    },
                },
                "results": results,
            },
        ],
    }


def sarif_to_string(sarif_doc: dict[str, Any]) -> str:
    """Serialize SARIF document to JSON string."""
    return json.dumps(sarif_doc, indent=2)
