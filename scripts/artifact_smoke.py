#!/usr/bin/env python3
"""Build and smoke-test the wheel and sdist release artifacts.

This is release tooling, not installed engine runtime. It requires the real
``build`` frontend and ``twine`` metadata checker supplied by the optional
``release`` extra; it never silently substitutes a backend or skips the gate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


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
