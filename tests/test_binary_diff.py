"""Binary changes must not be classified as source code."""

from unittest.mock import patch

import pytest

from ci_test_gate.classifier import LLMTestClassifier, TestClassifier
from ci_test_gate.context_builder import ContextBuilder
from ci_test_gate.diff_parser import DiffParser

TEXT = """diff --git a/src/main.py b/src/main.py
--- a/src/main.py
+++ b/src/main.py
@@ -1 +1 @@
-old
+new
"""
BINARY = """diff --git a/src/image.py b/src/image.py
Binary files a/src/image.py and b/src/image.py differ
"""


def test_no_newline_markers_are_not_hunk_content():
    change = DiffParser().parse(
        TEXT.replace("-old\n", "-old\n\\ No newline at end of file\n")
        + "\\ No newline at end of file\n"
    )[0]
    assert change.added_lines == ["new"]
    assert change.removed_lines == ["old"]
    assert change.hunks == ["-old\n+new"]


@pytest.mark.parametrize(
    "mode,marker",
    [
        ("", "Binary files a/src/image.py and b/src/image.py differ"),
        ("new file mode 100644\n", "Binary files /dev/null and b/src/image.py differ"),
        (
            "deleted file mode 100644\n",
            "Binary files a/src/image.py and /dev/null differ",
        ),
        ("", "GIT binary patch\nliteral 3\n+payload\n-payload\n"),
    ],
)
def test_binary_change_retains_path_and_mode_without_text(mode, marker):
    changes = DiffParser().parse(
        "diff --git a/src/image.py b/src/image.py\n" + mode + marker
    )
    assert len(changes) == 1
    change = changes[0]
    assert change.path == "src/image.py"
    assert change.is_binary
    assert change.is_new == mode.startswith("new")
    assert change.is_deleted == mode.startswith("deleted")
    assert change.added_lines == change.removed_lines == change.hunks == []


def test_mixed_diff_keeps_text_and_skips_binary_for_classification():
    parser = DiffParser()
    changes = parser.parse(
        BINARY + TEXT + BINARY.replace("src/image.py", "tests/test_image.py")
    )
    assert len(changes) == 3
    assert changes[1].added_lines == ["new"]
    assert not changes[1].is_binary
    assert [c.path for c in parser.get_non_test_changes(changes)] == ["src/main.py"]
    assert parser.get_test_changes(changes) == []
    context = ContextBuilder().build(changes)
    assert [c.path for c in context.changed_files] == ["src/main.py"]
    assert context.test_files_present == []
    rec = TestClassifier().classify(
        changes, context, ["tests/test_image.py", "tests/test_main.py"]
    )
    assert rec.required == ["tests/test_main.py"]
    classifier = LLMTestClassifier({"api_key": "unused-test-key"})
    with patch.object(classifier, "llm_classify") as classify:
        classifier.classify(changes, context)
    assert [c.path for c in classify.call_args.args[0]] == ["src/main.py"]


def test_binary_only_does_not_call_llm():
    changes = DiffParser().parse(BINARY)
    context = ContextBuilder().build(changes)
    classifier = LLMTestClassifier({"api_key": "unused-test-key"})
    with patch.object(classifier, "llm_classify") as classify:
        result = classifier.classify(changes, context, ["tests/test_image.py"])
    classify.assert_not_called()
    assert result.required == []
    assert result.optional == ["tests/test_image.py"]
