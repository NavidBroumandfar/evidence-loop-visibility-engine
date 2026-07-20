#!/usr/bin/env python3
"""Verify the exact package-version to Git-tag release identity."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path


def expected_tag(root: Path) -> str:
    document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
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
    except (OSError, RuntimeError, tomllib.TOMLDecodeError) as exc:
        print(f"release identity blocked: {exc}", file=sys.stderr)
        return 2
    if args.tag != required:
        print(f"release identity blocked: tag must be {required}", file=sys.stderr)
        return 2
    print(f"release identity valid: {required}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
