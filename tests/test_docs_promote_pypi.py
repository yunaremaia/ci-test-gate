"""Regression guard: the docs must offer the published PyPI package.

``ci-test-gate`` is published on PyPI (``.github/workflows/publish.yml`` builds
and uploads it), so the README must offer ``pip install ci-test-gate`` and
carry the PyPI version badge. Otherwise every visitor arriving from GitHub is
pushed towards cloning the repository instead of installing the release, which
hides real download numbers behind a fork-only install path.

These tests only read ``README.md``; they never touch the network, so they are
stable on every CI matrix leg.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"

PYPI_INSTALL = "pip install ci-test-gate"
PYPI_BADGE = "https://img.shields.io/pypi/v/ci-test-gate"
PYPI_PROJECT_URL = "https://pypi.org/project/ci-test-gate"
GIT_INSTALL_MARKER = "pip install git+"


@pytest.fixture(scope="module")
def readme() -> str:
    assert README.is_file(), f"README not found at {README}"
    return README.read_text(encoding="utf-8")


def test_readme_offers_pypi_install(readme: str) -> None:
    """The PyPI install path must be present in the README."""
    assert PYPI_INSTALL in readme, (
        f"README must document `{PYPI_INSTALL}` — the package is published on "
        "PyPI and the git install is the only path advertised otherwise"
    )


def test_readme_has_pypi_version_badge(readme: str) -> None:
    """The PyPI version badge must be present in the README."""
    assert PYPI_BADGE in readme, (
        f"README must carry the PyPI version badge ({PYPI_BADGE})"
    )


def test_pypi_badge_links_to_project_page(readme: str) -> None:
    """The badge must link to the PyPI project page, not a bare image."""
    assert PYPI_PROJECT_URL in readme, (
        f"the PyPI badge must link to {PYPI_PROJECT_URL}"
    )


def test_git_install_is_not_the_only_path(readme: str) -> None:
    """A ``pip install git+`` line is acceptable only alongside the PyPI one."""
    git_lines = [
        line for line in readme.splitlines() if GIT_INSTALL_MARKER in line
    ]
    if git_lines:
        assert PYPI_INSTALL in readme, (
            "README offers a git install "
            f"({git_lines[0].strip()!r}) without also offering "
            f"`{PYPI_INSTALL}`; the git install must stay an alternative, "
            "not the only documented path"
        )


def test_quickstart_block_leads_with_pypi_install(readme: str) -> None:
    """The first install command in the quickstart must be the PyPI one."""
    install_lines = [
        line.strip()
        for line in readme.splitlines()
        if line.strip().startswith("pip install ")
    ]
    assert install_lines, "README must document at least one pip install command"
    assert install_lines[0].startswith(PYPI_INSTALL), (
        "the first install command in the README must be the PyPI one, "
        f"found {install_lines[0]!r} instead"
    )