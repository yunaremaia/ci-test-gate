"""Tests for ci-test-gate LLM module."""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from ci_test_gate.context import AnalysisContext
from ci_test_gate.llm import (
    LLMConfig,
    _build_user_prompt,
    _fallback_classify,
    _find_test_candidates,
    classify_with_llm,
)
from ci_test_gate.models import Diff, DiffFile, Language, TestRisk, TestSuite


class TestLLMConfig:
    """Tests for LLMConfig class."""

    def test_default_init(self):
        config = LLMConfig()
        assert config.api_key == ""
        assert config.model == "gpt-4o-mini"
        assert config.base_url == "https://api.openai.com/v1"
        assert config.temperature == 0.1
        assert config.max_tokens == 2048

    def test_custom_init(self):
        config = LLMConfig(
            api_key="test-key",
            model="gpt-4",
            base_url="https://custom.api.com/v1",
            temperature=0.5,
            max_tokens=1024,
        )
        assert config.api_key == "test-key"
        assert config.model == "gpt-4"
        assert config.base_url == "https://custom.api.com/v1"
        assert config.temperature == 0.5
        assert config.max_tokens == 1024

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key-123")
        monkeypatch.setenv("CI_TEST_GATE_MODEL", "gpt-4-turbo")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://env.api.com/v1")
        config = LLMConfig.from_env()
        assert config.api_key == "env-key-123"
        assert config.model == "gpt-4-turbo"
        assert config.base_url == "https://env.api.com/v1"

    def test_from_env_defaults(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("CI_TEST_GATE_MODEL", raising=False)
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        config = LLMConfig.from_env()
        assert config.api_key == ""
        assert config.model == "gpt-4o-mini"
        assert config.base_url == "https://api.openai.com/v1"


class TestBuildUserPrompt:
    """Tests for _build_user_prompt function."""

    def test_basic_prompt(self):
        diff = Diff(files=[
            DiffFile(path="src/foo.py", additions=2, deletions=1),
        ])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=["test_foo.py"],
            test_framework="pytest",
        )
        prompt = _build_user_prompt(ctx)
        assert "src/foo.py" in prompt
        assert "pytest" in prompt
        assert "test_foo.py" in prompt

    def test_multiple_files(self):
        diff = Diff(files=[
            DiffFile(path="src/foo.py", additions=2, deletions=1),
            DiffFile(path="src/bar.py", additions=5, deletions=0),
        ])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=["test_foo.py", "test_bar.py"],
            test_framework="pytest",
        )
        prompt = _build_user_prompt(ctx)
        assert "src/foo.py" in prompt
        assert "src/bar.py" in prompt

    def test_no_test_files(self):
        diff = Diff(files=[DiffFile(path="src/foo.py", additions=1, deletions=0)])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=[],
            test_framework="pytest",
        )
        prompt = _build_user_prompt(ctx)
        assert "src/foo.py" in prompt

    def test_hunks_truncated(self):
        diff = Diff(files=[DiffFile(path="src/foo.py", additions=100, deletions=0)])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=["test_foo.py"],
            test_framework="pytest",
        )
        prompt = _build_user_prompt(ctx)
        assert "src/foo.py" in prompt


class TestFindTestCandidates:
    """Tests for _find_test_candidates."""

    def test_exact_match(self):
        candidates = _find_test_candidates("src/foo.py", ["test_foo.py", "test_bar.py"])
        assert "test_foo.py" in candidates

    def test_suffix_match(self):
        candidates = _find_test_candidates("src/users.py", ["users_test.py", "orders_test.py"])
        assert "users_test.py" in candidates

    def test_nested_and_prefixed_match(self):
        candidates = _find_test_candidates(
            "src/api/users.py",
            [
                "tests/unit/test_users.py",
                "tests/integration/test_api_users.py",
                "tests/api/users_test.py",
                "tests/unit/orders_test.py",
            ],
        )
        assert "tests/unit/test_users.py" in candidates
        assert "tests/integration/test_api_users.py" in candidates
        assert "tests/api/users_test.py" in candidates

    def test_dotted_test_suffix_match(self):
        candidates = _find_test_candidates(
            "src/api/users.py",
            ["tests/unit/users.test.ts", "tests/unit/users.spec.ts", "tests/unit/orders.test.ts"],
        )
        assert "tests/unit/users.test.ts" in candidates
        assert "tests/unit/users.spec.ts" in candidates

    def test_no_match(self):
        candidates = _find_test_candidates("src/foo.py", ["test_bar.py", "test_baz.py"])
        assert candidates == []

    def test_empty_test_files(self):
        candidates = _find_test_candidates("src/foo.py", [])
        assert candidates == []

    def test_max_five_results(self):
        # Should return at most 5 candidates
        test_files = [f"test_{i}.py" for i in range(10)]
        candidates = _find_test_candidates("src/test.py", test_files)
        assert len(candidates) <= 5


class TestFallbackClassify:
    """Tests for _fallback_classify."""

    def test_empty_diff(self):
        diff = Diff(files=[])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.UNKNOWN,
            file_contexts=[],
            test_files_in_repo=["test_foo.py"],
            test_framework="pytest",
        )
        result = _fallback_classify(ctx)
        # Empty diff still produces broad fallback when test files exist
        assert result.language == Language.UNKNOWN

    def test_test_file_changed(self):
        diff = Diff(files=[DiffFile(path="test_foo.py", additions=5, deletions=0)])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=["test_foo.py"],
            test_framework="pytest",
        )
        result = _fallback_classify(ctx)
        assert len(result.required) >= 1

    def test_source_file_changed(self):
        diff = Diff(files=[DiffFile(path="src/users.py", additions=2, deletions=1)])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=["test_users.py"],
            test_framework="pytest",
        )
        result = _fallback_classify(ctx)
        assert len(result.required) >= 1

    def test_broad_fallback(self):
        diff = Diff(files=[DiffFile(path="src/unknown.py", additions=1, deletions=0)])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=["test_foo.py", "test_bar.py", "test_baz.py"],
            test_framework="pytest",
        )
        result = _fallback_classify(ctx)
        # Should recommend broad set when no match found
        assert len(result.recommended) >= 1 or len(result.required) >= 1

    @pytest.mark.parametrize("config_path", ["pyproject.toml", "package.json", "Cargo.toml", "go.mod", "services/api/package.json"])
    def test_config_change_recommends_every_test(self, config_path):
        tests = [f"tests/test_module_{i}.py" for i in range(12)]
        ctx = AnalysisContext(
            diff=Diff(files=[DiffFile(path=config_path)]),
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=tests,
            test_framework="pytest",
        )

        result = _fallback_classify(ctx)

        assert [rec.suite.path for rec in result.recommended] == tests
        assert not result.required

    def test_config_change_preserves_direct_required_test(self):
        tests = ["tests/test_foo.py", "tests/test_bar.py"]
        ctx = AnalysisContext(
            diff=Diff(files=[DiffFile(path="pyproject.toml"), DiffFile(path="tests/test_foo.py")]),
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=tests,
            test_framework="pytest",
        )

        result = _fallback_classify(ctx)

        assert [rec.suite.path for rec in result.required] == ["tests/test_foo.py"]
        assert [rec.suite.path for rec in result.recommended] == ["tests/test_bar.py"]


class TestClassifyWithLLM:
    """Tests for classify_with_llm."""

    def test_no_api_key_falls_back(self):
        diff = Diff(files=[DiffFile(path="src/foo.py", additions=1, deletions=0)])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=["test_foo.py"],
            test_framework="pytest",
        )
        config = LLMConfig(api_key="", model="gpt-4o-mini")
        result = classify_with_llm(ctx, config)
        # Should fall back to rule-based
        assert result.language == Language.PYTHON
        assert "fallback" in result.summary.lower() or "Rule-based" in result.summary

    def test_successful_llm_call(self):
        """Test with mocked OpenAI client."""
        diff = Diff(files=[DiffFile(path="src/foo.py", additions=1, deletions=0)])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=["test_foo.py"],
            test_framework="pytest",
        )
        config = LLMConfig(api_key="test-key", model="gpt-4o-mini")

        mock_response = MagicMock()
        mock_response.choices[0].message.content = '{"recommendations": [{"path": "test_foo.py", "risk": "required", "reason": "Direct test", "confidence": 0.95}], "estimated_savings_seconds": 60, "summary": "Run test_foo.py"}'

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            result = classify_with_llm(ctx, config)
            assert len(result.recommendations) == 1
            assert result.recommendations[0].suite.path == "test_foo.py"
            assert result.estimated_savings == 60
            assert result.summary == "Run test_foo.py"

    def test_llm_exception_falls_back(self):
        """Test that exception falls back gracefully."""
        diff = Diff(files=[DiffFile(path="src/foo.py", additions=1, deletions=0)])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=["test_foo.py"],
            test_framework="pytest",
        )
        config = LLMConfig(api_key="test-key", model="gpt-4o-mini")

        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")

        with patch("openai.OpenAI", return_value=mock_client):
            result = classify_with_llm(ctx, config)
            assert result.language == Language.PYTHON
            assert "fallback" in result.summary.lower()

    def test_empty_llm_response(self):
        """Test empty response falls back."""
        diff = Diff(files=[DiffFile(path="src/foo.py", additions=1, deletions=0)])
        ctx = AnalysisContext(
            diff=diff,
            language=Language.PYTHON,
            file_contexts=[],
            test_files_in_repo=["test_foo.py"],
            test_framework="pytest",
        )
        config = LLMConfig(api_key="test-key", model="gpt-4o-mini")

        mock_response = MagicMock()
        mock_response.choices[0].message.content = ""

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response

        with patch("openai.OpenAI", return_value=mock_client):
            result = classify_with_llm(ctx, config)
            assert result.language == Language.PYTHON
            assert "fallback" in result.summary.lower()
