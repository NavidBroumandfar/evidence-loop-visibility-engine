#!/usr/bin/env python3
"""Deterministic scanner for the tracked public-release surface.

This is deliberately conservative about executable secrets and live effects,
while allowing synthetic fixtures to demonstrate the scanner itself. It has no
network access and reads only Git-tracked files (or an explicit root).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_SCAN_BYTES = 2 * 1024 * 1024
MARKER = "SYNTHETIC_SCANNER_TEST"

PRIVATE_PATH = re.compile(r"/(?:" + "Users" + r"|home|private/var|var/folders)(?:/|$)", re.I)
CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|auth(?:entication)?[_ -]?token|secret|password|private[_ -]?key)\s*[:=]\s*(?:[\"'][^\"']{4,}[\"']|[A-Za-z0-9_/+.-]{4,})"
)
PRIVATE_ID_PATTERN = re.compile(r"(?i)(?:" + "provider[_ -]?id|account[_ -]?id|project[_ -]?id" + r")\s*[:=]")
TOKEN_SHAPE = re.compile(r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
LIVE_IMPORT = re.compile(r"(?m)^\s*(?:import|from)\s+(?:http\.client|urllib(?:\.request)?|socket|requests|httpx|aiohttp|urllib3|selenium|playwright|boto3|paramiko)\b")
LIVE_CALL = re.compile(r"(?:os\.system|subprocess\.|http\.client|urllib(?:\.request)?\.|socket\.|requests\.|httpx\.|aiohttp\.|playwright|selenium|boto3|paramiko)")
UNSAFE_SCHEME = re.compile(r"(?i)(?:javascript" + ":|data" + ":|file" + ":|ftp" + ":|http" + "://)")
GENERATED_PART = re.compile(r"(?:^|/)(?:__pycache__|\.pytest_cache|\.mypy_cache|dist|build|[^/]+\.egg-info)(?:/|$)")


def _tracked_files(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
            text=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("unable to enumerate tracked release files") from exc
    names = [item for item in result.stdout.decode("utf-8").split("\0") if item]
    return [root / name for name in names]


def _decode_wrapped(value: str) -> str:
    if len(value) < 16 or len(value) % 4 or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", value):
        return ""
    try:
        return base64.b64decode(value, validate=True).decode("utf-8", "ignore")
    except (binascii.Error, ValueError):
        return ""


def scan(root_value: str | os.PathLike[str] = ".") -> list[dict[str, str]]:
    root = Path(root_value).resolve()
    findings: list[dict[str, str]] = []
    for path in _tracked_files(root):
        relative = path.relative_to(root).as_posix()
        if GENERATED_PART.search(relative):
            findings.append({"file": relative, "rule": "generated-artifact"})
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            findings.append({"file": relative, "rule": "unreadable"})
            continue
        if len(raw) > MAX_SCAN_BYTES:
            findings.append({"file": relative, "rule": "oversize-release-file"})
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            findings.append({"file": relative, "rule": "non-utf8-release-file"})
            continue
        # A controlled fixture may contain one intentional marker on the same
        # line as a synthetic secret test. It never bypasses unrelated rules.
        controlled_fixture = relative.startswith("tests/fixtures/") and MARKER in text
        runtime_surface = relative.startswith("src/evidence_loop/")
        checks = [
            (PRIVATE_PATH, "private-absolute-path"),
            (CREDENTIAL_ASSIGNMENT, "credential-assignment"),
            (PRIVATE_ID_PATTERN, "provider-private-id"),
            (TOKEN_SHAPE, "token-shape"),
            (LIVE_IMPORT, "live-provider-import"),
            (LIVE_CALL, "live-runtime-call"),
            (UNSAFE_SCHEME, "unsafe-link-scheme"),
        ]
        for pattern, rule in checks:
            if rule in {"live-provider-import", "live-runtime-call"} and not runtime_surface:
                continue
            for match in pattern.finditer(text):
                line_start = text.rfind("\n", 0, match.start()) + 1
                line_end = text.find("\n", match.end())
                line = text[line_start : line_end if line_end >= 0 else len(text)]
                if controlled_fixture and MARKER in line:
                    continue
                findings.append({"file": relative, "rule": rule})
        for wrapped_match in re.finditer(r"[A-Za-z0-9+/]{16,}={0,2}", text):
            candidate = wrapped_match.group(0)
            decoded = _decode_wrapped(candidate)
            line_start = text.rfind("\n", 0, wrapped_match.start()) + 1
            line_end = text.find("\n", wrapped_match.end())
            line = text[line_start : line_end if line_end >= 0 else len(text)]
            if decoded and (PRIVATE_PATH.search(decoded) or CREDENTIAL_ASSIGNMENT.search(decoded) or PRIVATE_ID_PATTERN.search(decoded)) and not (controlled_fixture and MARKER in line):
                findings.append({"file": relative, "rule": "wrapped-sensitive-marker"})
    return sorted(findings, key=lambda item: (item["file"], item["rule"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="scan tracked files for unsafe public-release content")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    findings = scan(args.root)
    if findings:
        for finding in findings:
            print(f"{finding['file']}: {finding['rule']}")
        return 1
    print("public release scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
