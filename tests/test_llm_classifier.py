"""Tests for LLMTestClassifier with mocked LLM responses."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ci_test_gate.classifier import (
    HeuristicTestClassifier,
    LLMTestClassifier,
    TestClassifier,
    TestRecommendation,
)
from ci_test_gate.context_builder import ChangeContext
from ci_test_gate.diff_parser import FileChange


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_changes(paths: list[str]) -> list[FileChange]:
    return [FileChange(path=p) for p in paths]


def _make_context() -> ChangeContext:
    return ChangeContext(changed_files=[])


def _make_llm_response(
    required: list[str] | None = None,
    recommended: list[str] | None = None,
    optional: list[str] | None = None,
    reasoning: str = "LLM reasoning",
    savings: int = 40,
) -> str:
    return json.dumps(
        {
            "required": required or [],
            "recommended": recommended or [],
            "optional": optional or [],
            "reasoning": reasoning,
            "estimated_savings_pct": savings,
        }
    )


def _mock_openai_response(content: str) -> MagicMock:
    """Build a minimal mock that matches openai.OpenAI().chat.completions.create()."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# LLMTestClassifier — happy path
# ---------------------------------------------------------------------------


class TestLLMTestClassifierHappyPath:
    """LLM returns valid JSON — recommendation is passed through verbatim."""

    def test_required_populated(self):
        llm_json = _make_llm_response(
            required=["tests/test_classifier.py"],
            reasoning="Direct test for changed classifier module",
            savings=60,
        )
        changes = _make_changes(["src/ci_test_gate/classifier.py"])
        context = _make_context()
        test_files = ["tests/test_classifier.py", "tests/test_cli.py"]

        classifier = LLMTestClassifier({"api_key": "sk-test"})

        with patch("ci_test_gate.classifier.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = _mock_openai_response(llm_json)

            rec = classifier.llm_classify(changes, context, test_files)

        assert "tests/test_classifier.py" in rec.required
        assert rec.reasoning == "Direct test for changed classifier module"
        assert rec.estimated_savings_pct == 60

    def test_recommended_populated(self):
        llm_json = _make_llm_response(
            recommended=["tests/test_cli.py"],
            reasoning="CLI tests touch changed module indirectly",
        )
        changes = _make_changes(["src/ci_test_gate/classifier.py"])
        context = _make_context()

        classifier = LLMTestClassifier({"api_key": "sk-test"})

        with patch("ci_test_gate.classifier.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = _mock_openai_response(llm_json)

            rec = classifier.llm_classify(changes, context, ["tests/test_cli.py"])

        assert "tests/test_cli.py" in rec.recommended

    def test_markdown_fences_stripped(self):
        """LLM wraps output in ```json … ``` — classifier must still parse it."""
        raw_json = _make_llm_response(required=["tests/test_foo.py"])
        fenced = f"```json\n{raw_json}\n```"

        changes = _make_changes(["src/foo.py"])
        context = _make_context()

        classifier = LLMTestClassifier({"api_key": "sk-test"})

        with patch("ci_test_gate.classifier.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = _mock_openai_response(fenced)

            rec = classifier.llm_classify(changes, context, ["tests/test_foo.py"])

        assert "tests/test_foo.py" in rec.required

    def test_model_selection_via_config(self):
        """The model name in config is forwarded to the OpenAI client."""
        llm_json = _make_llm_response()
        changes = _make_changes(["src/foo.py"])
        context = _make_context()

        classifier = LLMTestClassifier({"api_key": "sk-test", "model": "gpt-4o"})

        with patch("ci_test_gate.classifier.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = _mock_openai_response(llm_json)

            classifier.llm_classify(changes, context)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o"

    def test_model_selection_via_env(self, monkeypatch):
        """CI_TEST_GATE_MODEL env var is used when no model is set in config."""
        monkeypatch.setenv("CI_TEST_GATE_MODEL", "gpt-4-turbo")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env")

        llm_json = _make_llm_response()
        changes = _make_changes(["src/foo.py"])
        context = _make_context()

        classifier = LLMTestClassifier()  # no explicit config

        with patch("ci_test_gate.classifier.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = _mock_openai_response(llm_json)

            classifier.llm_classify(changes, context)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4-turbo"


# ---------------------------------------------------------------------------
# LLMTestClassifier — fallback behaviour
# ---------------------------------------------------------------------------


class TestLLMTestClassifierFallback:
    """LLM unavailable or broken — must degrade to the heuristic classifier."""

    def test_no_api_key_falls_back_to_heuristic(self, monkeypatch):
        """Without an API key the LLM path should not be called at all."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        changes = _make_changes(["src/ci_test_gate/classifier.py"])
        context = _make_context()
        test_files = ["tests/test_classifier.py"]

        classifier = LLMTestClassifier({})  # no api_key

        with patch("ci_test_gate.classifier.OpenAI") as mock_openai_cls:
            rec = classifier.llm_classify(changes, context, test_files)
            mock_openai_cls.assert_not_called()

        # Should still produce a sensible heuristic result
        assert isinstance(rec, TestRecommendation)
        # Heuristic should have matched the test file to the source module
        assert "tests/test_classifier.py" in rec.required

    def test_api_error_falls_back_to_heuristic(self):
        """When the OpenAI call raises an exception, heuristic result is returned."""
        changes = _make_changes(["src/ci_test_gate/classifier.py"])
        context = _make_context()
        test_files = ["tests/test_classifier.py"]

        classifier = LLMTestClassifier({"api_key": "sk-test"})

        with patch("ci_test_gate.classifier.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.side_effect = RuntimeError("connection refused")

            rec = classifier.llm_classify(changes, context, test_files)

        assert isinstance(rec, TestRecommendation)
        assert "LLM call failed" in rec.reasoning

    def test_invalid_json_falls_back_to_heuristic(self):
        """LLM returns malformed JSON — heuristic fallback is used."""
        changes = _make_changes(["src/ci_test_gate/cli.py"])
        context = _make_context()
        test_files = ["tests/test_cli.py"]

        classifier = LLMTestClassifier({"api_key": "sk-test"})

        with patch("ci_test_gate.classifier.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = _mock_openai_response(
                "Sorry, I cannot process that request."
            )

            rec = classifier.llm_classify(changes, context, test_files)

        assert isinstance(rec, TestRecommendation)
        # Should contain a fallback indicator in reasoning
        assert "LLM call failed" in rec.reasoning


# ---------------------------------------------------------------------------
# TestClassifier.classify() dispatch
# ---------------------------------------------------------------------------


class TestClassifierDispatch:
    """classifier_type='llm' routes through llm_classify()."""

    def test_classify_dispatches_to_llm(self):
        classifier = TestClassifier(classifier_type="llm")
        changes = _make_changes(["src/foo.py"])
        context = _make_context()

        with patch.object(classifier, "llm_classify", wraps=classifier.llm_classify) as spy:
            classifier.classify(changes, context)
            spy.assert_called_once()

    def test_classify_dispatches_to_heuristic(self):
        classifier = TestClassifier(classifier_type="heuristic")
        changes = _make_changes(["src/foo.py"])
        context = _make_context()

        with patch.object(
            classifier, "heuristic_classify", wraps=classifier.heuristic_classify
        ) as spy:
            classifier.classify(changes, context)
            spy.assert_called_once()


# ---------------------------------------------------------------------------
# CLI --llm flag
# ---------------------------------------------------------------------------


class TestCLILLMFlag:
    """End-to-end test for the --llm flag via main()."""

    def _run_suggest(self, extra_args: list[str], diff_text: str, monkeypatch) -> int:
        import tempfile
        from pathlib import Path

        from ci_test_gate.cli import main

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".diff", delete=False
        ) as f:
            f.write(diff_text)
            diff_path = f.name

        try:
            return main(["suggest", "--diff", diff_path] + extra_args)
        finally:
            Path(diff_path).unlink(missing_ok=True)

    def test_llm_flag_invokes_llm_classifier(self, monkeypatch):
        """With --llm, LLMTestClassifier.llm_classify is called."""
        llm_json = _make_llm_response(
            required=["tests/test_foo.py"], reasoning="LLM says so"
        )

        diff_text = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )

        with patch("ci_test_gate.classifier.OpenAI") as mock_openai_cls:
            mock_client = MagicMock()
            mock_openai_cls.return_value = mock_client
            mock_client.chat.completions.create.return_value = _mock_openai_response(llm_json)

            rc = self._run_suggest(
                ["--llm", "--llm-api-key", "sk-test", "--output", "json"],
                diff_text,
                monkeypatch,
            )

        assert rc == 0
        mock_client.chat.completions.create.assert_called_once()

    def test_no_llm_flag_uses_heuristic(self, monkeypatch):
        """Without --llm, the OpenAI client is never called."""
        diff_text = (
            "diff --git a/src/foo.py b/src/foo.py\n"
            "--- a/src/foo.py\n"
            "+++ b/src/foo.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )

        with patch("ci_test_gate.classifier.OpenAI") as mock_openai_cls:
            rc = self._run_suggest(["--output", "json"], diff_text, monkeypatch)
            mock_openai_cls.assert_not_called()

        assert rc == 0
