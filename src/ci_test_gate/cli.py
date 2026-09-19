"""CLI entry point for ci-test-gate."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ci_test_gate import __version__
from ci_test_gate.classifier import TestClassifier
from ci_test_gate.context_builder import ContextBuilder
from ci_test_gate.diff_parser import DiffParser


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ci-test-gate",
        description="LLM-powered test selection for CI — run only the tests that matter",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # `suggest` command
    suggest_parser = subparsers.add_parser("suggest", help="Suggest which tests to run")
    suggest_parser.add_argument(
        "--diff",
        type=Path,
        required=True,
        help="Path to diff file (or - for stdin)",
    )
    suggest_parser.add_argument(
        "--test-files",
        type=Path,
        help="File listing all test files (one per line)",
    )
    suggest_parser.add_argument(
        "--mode",
        choices=["suggest", "gate"],
        default="suggest",
        help="Output mode: suggest (comment) or gate (fail if required missing)",
    )
    suggest_parser.add_argument(
        "--output",
        choices=["json", "markdown", "sarif"],
        default="markdown",
        help="Output format",
    )

    # `local` command (pre-push validation)
    local_parser = subparsers.add_parser("local", help="Local pre-push validation (auto-discovers diff)")
    local_parser.add_argument(
        "--base",
        default="main",
        help="Base branch to diff against (default: main)",
    )
    local_parser.add_argument(
        "--mode",
        choices=["suggest", "gate"],
        default="suggest",
        help="Output mode: suggest (comment) or gate (fail if required missing)",
    )
    local_parser.add_argument(
        "--output",
        choices=["json", "markdown", "sarif"],
        default="markdown",
        help="Output format",
    )

    args = parser.parse_args(argv)

    if args.command == "suggest":
        return _handle_suggest(args)
    elif args.command == "local":
        return _handle_local(args)
    return 0


def _handle_local(args) -> int:
    """Handle the local command — auto-discovers diff against a base branch."""
    import subprocess

    # Run git diff to get changed files
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{args.base}...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        changed_files = [line for line in result.stdout.splitlines() if line]
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to get diff against {args.base}: {e.stderr}", file=sys.stderr)
        return 1

    if not changed_files:
        print("No changes detected.")
        return 0

    # Get diff content for classifier
    try:
        result = subprocess.run(
            ["git", "diff", f"{args.base}...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        diff_text = result.stdout
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Failed to get diff: {e.stderr}", file=sys.stderr)
        return 1

    # Discover test files
    try:
        test_result = subprocess.run(
            ["git", "ls-files", "tests/**", "test/**", "*_test.py", "*.test.ts", "*.test.js"],
            capture_output=True,
            text=True,
            check=True,
        )
        test_files = [line for line in test_result.stdout.splitlines() if line]
    except subprocess.CalledProcessError:
        test_files = []

    # Parse diff
    parser = DiffParser()
    changes = parser.parse(diff_text)

    # Build context
    builder = ContextBuilder()
    context = builder.build(changes)

    # Classify
    classifier = TestClassifier()
    recommendation = classifier.classify(changes, context, test_files or None)

    # Output
    if args.output == "json":
        print(recommendation.to_json())
    elif args.output == "sarif":
        from ci_test_gate.sarif import recommendation_to_sarif, sarif_to_string
        sarif_doc = recommendation_to_sarif(
            recommendation.required,
            recommendation.recommended,
            all_changed_files=[f.path for f in changes],
            tool_version=__version__,
        )
        print(sarif_to_string(sarif_doc))
    else:
        print(recommendation.to_markdown())

    # Gate mode: return non-zero if required tests are being skipped
    if args.mode == "gate":
        missing = [t for t in recommendation.required if t not in (test_files or [])]
        if missing:
            return 2  # Required tests not covered

    return 0


def _handle_suggest(args) -> int:
    """Handle the suggest command."""
    # Read diff
    if str(args.diff) == "-":
        diff_text = sys.stdin.read()
    else:
        diff_text = args.diff.read_text()

    # Parse diff
    parser = DiffParser()
    changes = parser.parse(diff_text)

    # Build context
    builder = ContextBuilder()
    context = builder.build(changes)

    # Read test files list
    test_files: list[str] = []
    if args.test_files:
        test_files = [line.strip() for line in args.test_files.read_text().splitlines() if line.strip()]

    # Classify
    classifier = TestClassifier()
    recommendation = classifier.classify(changes, context, test_files or None)

    # Output
    if args.output == "json":
        print(recommendation.to_json())
    elif args.output == "sarif":
        from ci_test_gate.sarif import recommendation_to_sarif, sarif_to_string
        sarif_doc = recommendation_to_sarif(
            recommendation.required,
            recommendation.recommended,
            all_changed_files=[f.path for f in changes],
            tool_version=__version__,
        )
        print(sarif_to_string(sarif_doc))
    else:
        print(recommendation.to_markdown())

    # Gate mode: return non-zero if required tests are being skipped
    if args.mode == "gate":
        missing = [t for t in recommendation.required if t not in (test_files or [])]
        if missing:
            return 2  # Required tests not covered

    return 0


if __name__ == "__main__":
    sys.exit(main())
