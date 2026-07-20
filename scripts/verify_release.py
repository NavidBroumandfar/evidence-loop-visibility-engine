#!/usr/bin/env python3
"""Verify the exact package-version to Git-tag release identity."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility for the test matrix.
    tomllib = None

PROJECT_HEADER = re.compile(r"(?m)^\s*\[project\]\s*(?:#.*)?$")
ANY_HEADER = re.compile(r"(?m)^\s*\[")
VERSION_FIELD = re.compile(r'(?m)^version\s*=\s*"([0-9A-Za-z][0-9A-Za-z.!+-]*)"\s*$')


def _fallback_project_version(text: str) -> str:
    """Parse the one supported Python 3.10 shape, rejecting ambiguous TOML."""
    if '"""' in text or "'''" in text:
        raise RuntimeError("Python 3.10 fallback rejects multiline TOML strings")
    headers = list(PROJECT_HEADER.finditer(text))
    if len(headers) != 1:
        raise RuntimeError("pyproject must contain exactly one physical [project] table")
    start = headers[0].end()
    next_header = ANY_HEADER.search(text, start)
    section = text[start : next_header.start() if next_header else len(text)]
    versions = VERSION_FIELD.findall(section)
    if len(versions) != 1:
        raise RuntimeError("pyproject project.version is missing or ambiguous")
    return versions[0]


def expected_tag(root: Path) -> str:
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    if tomllib is None:
        version = _fallback_project_version(text)
    else:
        try:
            document = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise RuntimeError("pyproject.toml is invalid") from exc
        version = document.get("project", {}).get("version")
        if not isinstance(version, str) or not version:
            raise RuntimeError("pyproject project.version is missing")
    return f"v{version}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="verify a release tag against the package version")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--tag", required=True)
    args = parser.parse_args(argv)
    try:
        required = expected_tag(Path(args.root).resolve())
    except (OSError, RuntimeError) as exc:
        print(f"release identity blocked: {exc}", file=sys.stderr)
        return 2
    if args.tag != required:
        print(f"release identity blocked: tag must be {required}", file=sys.stderr)
        return 2
    print(f"release identity valid: {required}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
