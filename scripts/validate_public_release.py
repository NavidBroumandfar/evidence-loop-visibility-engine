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
import xml.etree.ElementTree as ET
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
SVG_URL = re.compile(r"url\(\s*['\"]?([^)'\"\s]+)", re.I)
SVG_NAMESPACE = "http:" + "//www.w3.org/2000/svg"
XLINK_NAMESPACE = "http:" + "//www.w3.org/1999/xlink"
XML_NAMESPACE = "http:" + "//www.w3.org/XML/1998/namespace"
SVG_ACTIVE_PREAMBLE = re.compile(r"<\?\s*xml-stylesheet(?:\s|\?>)|<!\s*(?:DOCTYPE|ENTITY)\b", re.I)
SVG_ACTIVE_ELEMENTS = {
    "audio",
    "discard",
    "embed",
    "foreignobject",
    "handler",
    "iframe",
    "listener",
    "object",
    "script",
    "set",
    "video",
}


def _svg_findings(text: str) -> set[str]:
    """Return structural safety findings for a public SVG document."""
    findings: set[str] = set()
    if SVG_ACTIVE_PREAMBLE.search(text):
        # Do not hand a declaration with entity expansion potential to the XML
        # parser. Stylesheet processing instructions are active content too.
        findings.add("active-svg-content")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I):
            return findings
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        findings.add("invalid-svg-xml")
        return findings
    if root.tag.rsplit("}", 1)[-1] != "svg":
        findings.add("invalid-svg-root")
        return findings
    for element in root.iter():
        local_tag = element.tag.rsplit("}", 1)[-1].lower()
        if local_tag in SVG_ACTIVE_ELEMENTS or local_tag.startswith("animate"):
            findings.add("active-svg-content")
        for raw_name, value in element.attrib.items():
            name = raw_name.rsplit("}", 1)[-1].lower()
            normalized = value.strip()
            if name.startswith("on"):
                findings.add("active-svg-content")
            if raw_name == f"{{{XML_NAMESPACE}}}base" and normalized and not normalized.startswith("#"):
                findings.add("external-svg-reference")
            if name == "href" and normalized and not normalized.startswith("#"):
                findings.add("external-svg-reference")
            for match in SVG_URL.finditer(normalized):
                if not match.group(1).startswith("#"):
                    findings.add("external-svg-reference")
        if local_tag == "style" and element.text:
            if "@import" in element.text.lower() or any(
                not match.group(1).startswith("#") for match in SVG_URL.finditer(element.text)
            ):
                findings.add("external-svg-reference")
    return findings


def _has_symlink_component(root: Path, path: Path) -> bool:
    """Check the tracked path itself and every repository-relative ancestor."""
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


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
        if _has_symlink_component(root, path):
            # Never follow a release-surface link: the target may be outside
            # the repository and its bytes must not influence the findings.
            findings.append({"file": relative, "rule": "symlink-release-path"})
            continue
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
        if path.suffix.lower() == ".svg":
            findings.extend(
                {"file": relative, "rule": rule}
                for rule in sorted(_svg_findings(text))
            )
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
                if (
                    rule == "unsafe-link-scheme"
                    and path.suffix.lower() == ".svg"
                    and any(
                        text.startswith(namespace, match.start())
                        for namespace in (SVG_NAMESPACE, XLINK_NAMESPACE)
                    )
                ):
                    # SVG 1.1 requires this identifier as its namespace. It is
                    # not a fetched resource or an active external reference.
                    continue
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
