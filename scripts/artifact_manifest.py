#!/usr/bin/env python3
"""Create and verify a closed SHA-256 manifest for release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path, PurePosixPath


ENTRY = re.compile(r"([0-9a-f]{64})  (dist/[A-Za-z0-9][A-Za-z0-9_.+-]*)")
MAX_MANIFEST_BYTES = 4096


def _artifact_set(dist: Path) -> list[Path]:
    if dist.is_symlink() or not dist.is_dir():
        raise RuntimeError("dist must be a real directory")
    entries = sorted(dist.iterdir(), key=lambda path: path.name)
    if any(path.is_symlink() or not path.is_file() for path in entries):
        raise RuntimeError("dist contains a symlink or non-regular entry")
    wheels = [path for path in entries if path.name.endswith(".whl")]
    sdists = [path for path in entries if path.name.endswith(".tar.gz")]
    if len(entries) != 2 or len(wheels) != 1 or len(sdists) != 1:
        raise RuntimeError("dist must contain exactly one wheel and one source distribution")
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.+-]*", path.name) for path in entries):
        raise RuntimeError("dist contains an unsafe artifact name")
    return entries


def write_digest_manifest(dist: Path, manifest: Path, root: Path) -> None:
    root = root.resolve()
    artifacts = _artifact_set(dist)
    lines: list[str] = []
    for artifact in artifacts:
        relative = artifact.resolve().relative_to(root)
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        lines.append(f"{digest}  {relative.as_posix()}")
    manifest.write_text("\n".join(lines) + "\n", encoding="ascii")


def verify_digest_manifest(root: Path, manifest: Path) -> None:
    root = root.resolve()
    dist = root / "dist"
    artifacts = _artifact_set(dist)
    if manifest.is_symlink() or not manifest.is_file():
        raise RuntimeError("artifact manifest must be a regular file")
    if manifest.stat().st_size > MAX_MANIFEST_BYTES:
        raise RuntimeError("artifact manifest is oversized")
    try:
        lines = manifest.read_text(encoding="ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise RuntimeError("artifact manifest must be ASCII") from exc
    if len(lines) != 2:
        raise RuntimeError("artifact manifest must contain exactly two entries")

    expected: dict[str, str] = {}
    for line in lines:
        match = ENTRY.fullmatch(line)
        if not match:
            raise RuntimeError("artifact manifest contains an unsafe entry")
        digest, raw_path = match.groups()
        relative = PurePosixPath(raw_path)
        if relative.parts != ("dist", relative.name) or raw_path in expected:
            raise RuntimeError("artifact manifest contains an unsafe or duplicate path")
        expected[raw_path] = digest

    actual = {f"dist/{path.name}": path for path in artifacts}
    if set(expected) != set(actual):
        raise RuntimeError("artifact manifest does not match the complete dist file set")
    for raw_path, path in actual.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected[raw_path]:
            raise RuntimeError("artifact digest mismatch")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="verify a closed release-artifact manifest")
    parser.add_argument("--root", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args(argv)
    try:
        verify_digest_manifest(Path(args.root), Path(args.manifest))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"artifact manifest blocked: {exc}", file=sys.stderr)
        return 2
    print("artifact manifest: exact wheel and sdist verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
