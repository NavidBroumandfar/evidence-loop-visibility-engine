#!/usr/bin/env python3
"""Build and smoke-test the wheel and sdist release artifacts.

This is release tooling, not installed engine runtime. It requires the real
``build`` frontend and ``twine`` metadata checker supplied by the optional
``release`` extra; it never silently substitutes a backend or skips the gate.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit


MAX_SDIST_MEMBERS = 4096
MAX_SDIST_MEMBER_BYTES = 4 * 1024 * 1024
MAX_SDIST_TOTAL_BYTES = 32 * 1024 * 1024
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)")


def _run(command: list[str], *, cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=capture)


def preflight(python: str = sys.executable) -> None:
    missing: list[str] = []
    for module, package in (("build", "build>=1.2"), ("twine", "twine>=5.1")):
        result = subprocess.run([python, "-c", f"import {module}"], capture_output=True, text=True)
        if result.returncode:
            missing.append(package)
    if missing:
        raise RuntimeError(
            "artifact-smoke requires the release tools; run `.venv/bin/pip install -e '.[release]'` "
            f"(missing: {', '.join(missing)})"
        )


def _safe_unpack_sdist(artifact: Path, destination: Path) -> Path:
    """Unpack a small, regular-file-only sdist under one top-level directory."""
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(artifact, "r:gz") as archive:
        members = archive.getmembers()
        if not members or len(members) > MAX_SDIST_MEMBERS:
            raise RuntimeError("sdist has an invalid or excessive member count")
        if any(member.size > MAX_SDIST_MEMBER_BYTES for member in members):
            raise RuntimeError("sdist contains an oversized member")
        if sum(member.size for member in members) > MAX_SDIST_TOTAL_BYTES:
            raise RuntimeError("sdist expands beyond the validation limit")

        seen: set[PurePosixPath] = set()
        roots: set[str] = set()
        for member in members:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
                raise RuntimeError("sdist contains an unsafe member path")
            if relative in seen:
                raise RuntimeError("sdist contains a duplicate member path")
            seen.add(relative)
            roots.add(relative.parts[0])
            if not (member.isdir() or member.isfile()):
                raise RuntimeError("sdist contains a link or special member")

            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise RuntimeError("sdist member could not be read")
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=64 * 1024)

    if len(roots) != 1:
        raise RuntimeError("sdist must contain one top-level directory")
    return destination / next(iter(roots))


def check_sdist_readme_links(artifact: Path, destination: Path) -> None:
    """Require every relative Markdown target in the long description."""
    package_root = _safe_unpack_sdist(artifact, destination)
    readme = package_root / "README.md"
    if not readme.is_file():
        raise RuntimeError("sdist is missing README.md")
    text = readme.read_text(encoding="utf-8")
    for raw_target in MARKDOWN_LINK.findall(text):
        parsed = urlsplit(raw_target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        relative = PurePosixPath(unquote(parsed.path))
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"README has an unsafe relative target: {raw_target}")
        if not package_root.joinpath(*relative.parts).is_file():
            raise RuntimeError(f"sdist is missing README target: {raw_target}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="build and smoke-test wheel and source distribution")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        preflight(sys.executable)
        with tempfile.TemporaryDirectory(prefix="evidence-loop-artifacts-") as temp:
            temp_root = Path(temp)
            out = temp_root / "dist"
            out.mkdir()
            # One build invocation creates both artifacts from a temporary cwd.
            _run([sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(out), str(root)], cwd=temp_root)
            artifacts = sorted(out.glob("*.whl")) + sorted(out.glob("*.tar.gz"))
            if len(artifacts) != 2:
                raise RuntimeError("artifact-smoke expected exactly one wheel and one source distribution")
            sdist = next(path for path in artifacts if path.name.endswith(".tar.gz"))
            check_sdist_readme_links(sdist, temp_root / "unpacked-sdist")
            _run([sys.executable, "-m", "twine", "check", *(str(path) for path in artifacts)], cwd=temp_root)
            input_file = root / "examples" / "normal.json"
            for artifact in artifacts:
                kind = "wheel" if artifact.suffix == ".whl" else "sdist"
                env = temp_root / f"venv-{kind}"
                _run([sys.executable, "-m", "venv", str(env)], cwd=temp_root)
                vpy = env / "bin" / "python"
                install_command = [str(vpy), "-m", "pip", "install", "--no-deps", str(artifact)]
                if kind == "wheel":
                    install_command.insert(4, "--no-index")
                _run(install_command, cwd=temp_root)
                _run([str(vpy), "-m", "evidence_loop", "validate", "--input", str(input_file)], cwd=temp_root)
                _run([str(vpy), "-m", "evidence_loop", "run", "--input", str(input_file), "--output", str(temp_root / f"run-{kind}")], cwd=temp_root)
                _run([str(vpy), "-m", "evidence_loop", "demo", "--output", str(temp_root / f"demo-{kind}")], cwd=temp_root)
                result = _run([str(vpy), "-m", "evidence_loop", "benchmark"], cwd=temp_root, capture=True)
                summary = json.loads(result.stdout)
                if summary.get("suite") != "deterministic-public-conformance-v1" or summary.get("passed") != summary.get("total"):
                    raise RuntimeError(f"artifact benchmark failed for {kind}")
    except RuntimeError as exc:
        print(f"artifact-smoke blocked: {exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError:
        print("artifact-smoke blocked: release tooling/build step failed; inspect the build output", file=sys.stderr)
        return 2
    print("artifact smoke: wheel and sdist metadata/install/validate/run/demo/benchmark passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
