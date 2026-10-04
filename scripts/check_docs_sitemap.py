#!/usr/bin/env python3
"""Fail if the built documentation site has an empty or incomplete sitemap.

Why this exists
---------------
mkdocs only emits ``<url>`` entries into ``sitemap.xml`` when ``site_url`` is
configured. Without it the build still succeeds, ``sitemap.xml`` is still
written, and the file is a valid but EMPTY ``<urlset>``:

    <?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    </urlset>

That is not hypothetical here. The sibling repository
``yunaremaia/driftcheck`` published an empty sitemap for months with a green
build the whole time -- nothing was red, so nothing got fixed. This script runs
in the ``docs`` CI job immediately after ``mkdocs build``, i.e. in the one place
where mkdocs is actually installed, so it checks the real artifact instead of
re-deriving what mkdocs would have produced.

The companion guard ``tests/test_mkdocs_site_url.py`` asserts the config half
without needing mkdocs or PyYAML (neither is a dependency of this project, so
neither may be imported from the test suite).

Only the standard library is used: this runs as a bare script in CI, where the
only guarantee available is the runner's Python.
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

# `nav:` entries look like `  - Home: index.md`. Nested sub-sections add more
# indentation but the same shape, so one regex over the whole nav block collects
# every target regardless of depth.
NAV_TARGET_RE = re.compile(r"^\s*-\s+[^:]*:\s*(?P<target>[^\s#]+\.md)\s*$")

# A top-level `key: value` line. Used to find where `nav:` starts and stops.
TOP_LEVEL_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][\w-]*):\s*(?P<value>.*)$")


def parse_site_url(text: str) -> str | None:
    """Return the top-level ``site_url`` value, or None when it is absent.

    Parsed as text rather than with PyYAML on purpose: PyYAML is not a
    dependency of this project, and YAML 1.1 also turns a bare ``on:`` key into
    the boolean ``True``.
    """
    for line in text.splitlines():
        match = TOP_LEVEL_KEY_RE.match(line)
        if match and match.group("key") == "site_url":
            return match.group("value").strip().strip("'\"") or None
    return None


def parse_nav_targets(text: str) -> list[str]:
    """Return every markdown file referenced by the ``nav:`` block."""
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        match = TOP_LEVEL_KEY_RE.match(line)
        if match and match.group("key") == "nav":
            start = index + 1
            break
    if start is None:
        return []

    targets: list[str] = []
    for line in lines[start:]:
        # A new top-level key ends the nav block.
        if line and not line[0].isspace() and TOP_LEVEL_KEY_RE.match(line):
            break
        target = NAV_TARGET_RE.match(line)
        if target:
            targets.append(target.group("target"))
    return targets


def expected_urls(site_url: str, nav_targets: list[str]) -> list[str]:
    """Map nav targets to the URLs mkdocs publishes them at.

    ``index.md`` becomes the site root and every other page becomes a directory
    URL under it, which is mkdocs' default (``use_directory_urls: true``).
    """
    base = site_url if site_url.endswith("/") else site_url + "/"
    urls = []
    for target in nav_targets:
        stem = target[: -len(".md")]
        if stem == "index":
            urls.append(base)
        else:
            urls.append(f"{base}{stem}/")
    return urls


def sitemap_urls(sitemap_path: Path) -> list[str]:
    root = ET.parse(sitemap_path).getroot()
    return [loc.text.strip() for loc in root.iter(f"{SITEMAP_NS}loc") if loc.text]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="repository root")
    parser.add_argument(
        "--site-dir",
        default="site",
        help="directory written by `mkdocs build`",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    site_dir = Path(args.site_dir)
    if not site_dir.is_absolute():
        site_dir = repo_root / site_dir

    config_path = repo_root / "mkdocs.yml"
    config_text = config_path.read_text(encoding="utf-8")

    failures: list[str] = []

    site_url = parse_site_url(config_text)
    if not site_url:
        failures.append(
            "mkdocs.yml defines no site_url: mkdocs then writes sitemap.xml as "
            "a valid but EMPTY urlset and emits no canonical link tags"
        )
        site_url = ""

    nav_targets = parse_nav_targets(config_text)
    if not nav_targets:
        failures.append("mkdocs.yml defines no nav: entries to check")

    # Every nav target must exist, or mkdocs' build fails on a missing page and
    # the expected URL list below would describe a site that cannot be built.
    for target in nav_targets:
        if not (repo_root / "docs" / target).is_file():
            failures.append(f"nav target docs/{target} does not exist")

    sitemap_path = site_dir / "sitemap.xml"
    if not sitemap_path.is_file():
        failures.append(f"{sitemap_path} was not produced by the build")
    else:
        published = sitemap_urls(sitemap_path)
        if not published:
            failures.append(
                f"{sitemap_path} contains zero <url> entries: the site is "
                "invisible to sitemap-based discovery"
            )
        expected = expected_urls(site_url, nav_targets) if site_url else []
        for url in expected:
            if url not in published:
                failures.append(f"sitemap.xml has no entry for {url}")

    if failures:
        print("docs sitemap check FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        f"docs sitemap check passed: {sitemap_path} lists {len(nav_targets)} "
        f"URL(s) under {site_url}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
