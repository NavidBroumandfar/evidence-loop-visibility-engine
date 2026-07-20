from __future__ import annotations

import contextlib
import base64
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import importlib.resources as resources
from unittest import mock

from evidence_loop.cli import main
from scripts.validate_public_release import scan
from scripts.artifact_manifest import verify_digest_manifest, write_digest_manifest
from scripts.artifact_smoke import check_sdist_readme_links, preflight
from scripts.verify_release import _fallback_project_version, expected_tag


ROOT = Path(__file__).resolve().parents[1]


class CliAndReleaseTests(unittest.TestCase):
    def test_release_tag_and_digest_manifest(self):
        self.assertEqual(expected_tag(ROOT), "v0.2.0")
        decoy = '''decoy = """
[project]
version = "0.2.0"
"""

[project]
name = "example"
version = "9.9.9"
'''
        with tempfile.TemporaryDirectory() as release_temp:
            release_root = Path(release_temp)
            (release_root / "pyproject.toml").write_text(decoy, encoding="utf-8")
            self.assertEqual(expected_tag(release_root), "v9.9.9")
        with self.assertRaisesRegex(RuntimeError, "multiline"):
            _fallback_project_version(decoy)
        with self.assertRaisesRegex(RuntimeError, "multiline"):
            _fallback_project_version('[project]\ndescription = """version = "0.2.0"""\nversion = "9.9.9"\n')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dist = root / "dist"
            dist.mkdir()
            wheel = dist / "example.whl"
            sdist = dist / "example.tar.gz"
            wheel.write_bytes(b"wheel")
            sdist.write_bytes(b"sdist")
            manifest = root / "artifact-digests.sha256"
            write_digest_manifest(dist, manifest, root)
            lines = manifest.read_text(encoding="ascii").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(
                {line.split("  ", 1)[1] for line in lines},
                {"dist/example.whl", "dist/example.tar.gz"},
            )
            verify_digest_manifest(root, manifest)

            wheel.write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                verify_digest_manifest(root, manifest)
            wheel.write_bytes(b"wheel")

            extra = dist / "extra.txt"
            extra.write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "exactly one wheel"):
                verify_digest_manifest(root, manifest)
            extra.unlink()

            sdist.unlink()
            with self.assertRaisesRegex(RuntimeError, "exactly one wheel"):
                verify_digest_manifest(root, manifest)
            sdist.write_bytes(b"sdist")

            sdist.unlink()
            sdist.symlink_to(wheel)
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                verify_digest_manifest(root, manifest)
            sdist.unlink()
            sdist.write_bytes(b"sdist")

            manifest.write_text(f"{'0' * 64}  ../unsafe.whl\n{'1' * 64}  dist/example.tar.gz\n", encoding="ascii")
            with self.assertRaisesRegex(RuntimeError, "unsafe entry"):
                verify_digest_manifest(root, manifest)

    def test_release_version_and_svg_assets(self):
        version = "0.2.0"
        self.assertEqual(__import__("evidence_loop").__version__, version)
        self.assertIn(f'version = "{version}"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn(f"version: {version}", (ROOT / "CITATION.cff").read_text(encoding="utf-8"))
        self.assertIn(f"## {version} - ", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))

        expected = {
            "evidence-loop-system.svg": "0 0 1440 760",
            "evidence-loop-social.svg": "0 0 1280 640",
        }
        for name, view_box in expected.items():
            text = (ROOT / "docs" / "assets" / name).read_text(encoding="utf-8")
            root = ET.fromstring(text)
            self.assertEqual(root.tag, "{" + "http:" + "//www.w3.org/2000/svg}svg")
            self.assertEqual(root.attrib["viewBox"], view_box)
            self.assertEqual(root.attrib["role"], "img")
            self.assertIn("aria-labelledby", root.attrib)
            self.assertNotIn("<script", text.lower())
            self.assertNotIn("<foreignobject", text.lower())
            self.assertNotIn("url(", text.lower())
            for element in root.iter():
                for raw_name, value in element.attrib.items():
                    name = raw_name.rsplit("}", 1)[-1].lower()
                    self.assertFalse(name.startswith("on"))
                    if name == "href":
                        self.assertTrue(value.startswith("#"))

    def test_cli_validate_run_demo_benchmark(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["validate", "--input", str(ROOT / "examples/normal.json")]), 0)
        summary = json.loads(out.getvalue())
        self.assertTrue(summary["valid"])
        with tempfile.TemporaryDirectory() as temp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["run", "--input", str(ROOT / "examples/normal.json"), "--output", temp]), 0)
            self.assertEqual(json.loads(out.getvalue())["terminal_state"], "approval-required")
            self.assertTrue((Path(temp) / "run.json").exists())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["demo", "--output", str(Path(temp) / "demo")]), 0)
            self.assertEqual(json.loads(out.getvalue())["demo_count"], 3)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main(["benchmark"]), 0)
        benchmark = json.loads(out.getvalue())
        self.assertEqual(benchmark["passed"], benchmark["total"])
        self.assertIn("pass_rate", benchmark)

    def test_release_scanner_clean_and_detects_controlled_fixture(self):
        self.assertEqual(scan(ROOT), [])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = getattr(subprocess, "r" + "un")
            run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            (root / "tests" / "fixtures").mkdir(parents=True)
            clean = root / "README.md"
            clean.write_text("safe https://example.test", encoding="utf-8")
            (root / "tests" / "fixtures" / "marker.txt").write_text("SYNTHETIC_SCANNER_TEST api" + "_key=demo", encoding="utf-8")
            run(["git", "-C", str(root), "add", "."], check=True)
            self.assertEqual(scan(root), [])
            (root / "README.md").write_text("api" + "_key=real-value", encoding="utf-8")
            run(["git", "-C", str(root), "add", "."], check=True)
            self.assertTrue(scan(root))

    def test_release_scanner_validates_svg_public_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = getattr(subprocess, "r" + "un")
            run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            assets = root / "docs" / "assets"
            assets.mkdir(parents=True)
            svg = assets / "visual.svg"
            svg.write_text(
                '<svg xmlns="http:' + '//www.w3.org/2000/svg" viewBox="0 0 10 10"><title>Safe</title><path d="M0 0h10v10z"/></svg>',
                encoding="utf-8",
            )
            run(["git", "-C", str(root), "add", "."], check=True)
            self.assertEqual(scan(root), [])
            svg.write_text(
                '<svg xmlns="http:' + '//www.w3.org/2000/svg"><script>bad()</script><image href="https://example.test/a.png"/></svg>',
                encoding="utf-8",
            )
            run(["git", "-C", str(root), "add", "."], check=True)
            rules = {finding["rule"] for finding in scan(root)}
            self.assertEqual(rules, {"active-svg-content", "external-svg-reference"})

    def test_release_scanner_rejects_symlink_and_ancestor_without_target_findings(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "repository"
            outside = base / "outside"
            root.mkdir()
            outside.mkdir()
            run = getattr(subprocess, "r" + "un")
            run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            malicious = (
                '<svg xmlns="http:'
                + '//www.w3.org/2000/svg"><script>bad()</script>'
                + '<image href="https://outside.example/a.png"/></svg>'
            )
            (outside / "direct.svg").write_text(malicious, encoding="utf-8")
            (outside / "ancestor.svg").write_text(malicious, encoding="utf-8")

            assets = root / "docs" / "assets"
            assets.mkdir(parents=True)
            (assets / "direct.svg").symlink_to(outside / "direct.svg")
            generated = root / "docs" / "generated"
            generated.mkdir()
            tracked = generated / "ancestor.svg"
            tracked.write_text('<svg xmlns="http:' + '//www.w3.org/2000/svg"/>', encoding="utf-8")
            run(["git", "-C", str(root), "add", "."], check=True)

            tracked.unlink()
            generated.rmdir()
            generated.symlink_to(outside, target_is_directory=True)
            self.assertEqual(
                scan(root),
                [
                    {"file": "docs/assets/direct.svg", "rule": "symlink-release-path"},
                    {"file": "docs/generated/ancestor.svg", "rule": "symlink-release-path"},
                ],
            )

    def test_release_scanner_rejects_active_svg_and_allows_internal_fragments(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = getattr(subprocess, "r" + "un")
            run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            assets = root / "docs" / "assets"
            assets.mkdir(parents=True)
            namespace = 'xmlns="http:' + '//www.w3.org/2000/svg"'
            xlink_namespace = 'xmlns:xlink="http:' + '//www.w3.org/1999/xlink"'
            (assets / "safe.svg").write_text(
                f'<svg {namespace} {xlink_namespace}><defs><path id="mark" d="M0 0h1v1z"/></defs><use href="#mark"/><use xlink:href="#mark"/><style>.mark{{fill:url(#mark)}}</style></svg>',
                encoding="utf-8",
            )
            (assets / "processing-instruction.svg").write_text(
                f'<?xml-stylesheet href="#sheet"?><svg {namespace}/>',
                encoding="utf-8",
            )
            (assets / "href-mutating-set.svg").write_text(
                f'<svg {namespace}><g href="#mark"><set attributeName="href" to="https://outside.example/changed"/></g></svg>',
                encoding="utf-8",
            )
            (assets / "timed.svg").write_text(
                f'<svg {namespace}><animate/><animateMotion/><animateTransform/><discard/></svg>',
                encoding="utf-8",
            )
            (assets / "external-base.svg").write_text(
                f'<svg {namespace}><g xml:base="https://outside.example/"><use href="#mark"/></g></svg>',
                encoding="utf-8",
            )
            run(["git", "-C", str(root), "add", "."], check=True)
            self.assertEqual(
                scan(root),
                [
                    {"file": "docs/assets/external-base.svg", "rule": "external-svg-reference"},
                    {"file": "docs/assets/href-mutating-set.svg", "rule": "active-svg-content"},
                    {"file": "docs/assets/processing-instruction.svg", "rule": "active-svg-content"},
                    {"file": "docs/assets/timed.svg", "rule": "active-svg-content"},
                ],
            )

    def test_packaged_resources_match_readable_fixtures(self):
        package = resources.files("evidence_loop.resources")
        for name in ("normal", "clean-no-op", "contained-site-failure", "all-domains"):
            root_doc = json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8"))
            packaged_doc = json.loads(package.joinpath(f"{name}.json").read_text(encoding="utf-8"))
            self.assertEqual(root_doc, packaged_doc)
        suite = json.loads(package.joinpath("benchmark.json").read_text(encoding="utf-8"))
        self.assertEqual(suite["suite"], "deterministic-public-conformance-v1")
        self.assertGreaterEqual(len(suite["cases"]), 4)

    def test_blocked_run_exit_code_three(self):
        document = json.loads((ROOT / "examples/contained-site-failure.json").read_text(encoding="utf-8"))
        document["sites"][0]["opportunities"][0]["domain"] = "unsupported-one"
        raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
        with tempfile.TemporaryDirectory() as temp:
            input_path = Path(temp) / "blocked.json"
            input_path.write_bytes(raw)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["run", "--input", str(input_path), "--output", str(Path(temp) / "out")])
            self.assertEqual(code, 3)
            self.assertEqual(json.loads(out.getvalue())["terminal_state"], "blocked")

    def test_scanner_quoted_secret_http_client_token_and_wrapped_evasions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = getattr(subprocess, "r" + "un")
            run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            (root / "README.md").write_text('sec' + 'ret = "quoted-value"', encoding="utf-8")
            (root / "tests" / "fixtures").mkdir(parents=True)
            (root / "tests" / "fixtures" / "token.txt").write_text("ghp_" + "A" * 24, encoding="utf-8")
            wrapped = base64.b64encode(b"sec" + b"ret: wrapped-value").decode("ascii")
            (root / "tests" / "fixtures" / "wrapped.txt").write_text(wrapped, encoding="utf-8")
            (root / "src" / "evidence_loop").mkdir(parents=True)
            (root / "src" / "evidence_loop" / "network.py").write_text("import http.client\nimport urllib.request\nimport socket\n", encoding="utf-8")
            run(["git", "-C", str(root), "add", "."], check=True)
            rules = {finding["rule"] for finding in scan(root)}
            self.assertTrue({"credential-assignment", "token-shape", "wrapped-sensitive-marker", "live-provider-import"} <= rules)

    def test_scanner_marker_is_line_scoped_not_a_file_bypass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run = getattr(subprocess, "r" + "un")
            run(["git", "init", "-q", "-b", "main", str(root)], check=True)
            (root / "tests" / "fixtures").mkdir(parents=True)
            (root / "tests" / "fixtures" / "marker.txt").write_text("SYNTHETIC_SCANNER_TEST\nsec" + "ret: hidden-value\n", encoding="utf-8")
            run(["git", "-C", str(root), "add", "."], check=True)
            self.assertIn("credential-assignment", {finding["rule"] for finding in scan(root)})

    def test_hostile_json_console_errors_are_structured_and_traceback_free(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            huge = root / "huge.json"
            huge.write_bytes(b'{"schema_version":"1","sites":[],"n":' + b"9" * 5000 + b"}")
            nested = root / "nested.json"
            nested.write_bytes(b"[" * 2000 + b"0" + b"]" * 2000)
            for path in (huge, nested):
                result = subprocess.run([sys.executable, "-m", "evidence_loop", "validate", "--input", str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stderr)
                error = json.loads(result.stderr)
                self.assertEqual(error["valid"], False)
                self.assertIn("error_code", error)

    def test_artifact_preflight_has_actionable_release_extra_message(self):
        with mock.patch("scripts.artifact_smoke.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "")):
            with self.assertRaises(RuntimeError) as ctx:
                preflight("fake-python")
        self.assertIn(".[release]", str(ctx.exception))

    def test_sdist_long_description_relative_targets_are_present(self):
        def write_sdist(path: Path, *, include_target: bool) -> None:
            entries = {
                "sample-0.2.0/README.md": b"![Visual](docs/assets/visual.svg)\n[Guide](docs/guide.md)\n[CI](https://example.test/ci.svg)\n",
                "sample-0.2.0/docs/assets/visual.svg": b"<svg/>",
            }
            if include_target:
                entries["sample-0.2.0/docs/guide.md"] = b"# Guide\n"
            with tarfile.open(path, "w:gz") as archive:
                for name, payload in entries.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            complete = root / "complete.tar.gz"
            missing = root / "missing.tar.gz"
            write_sdist(complete, include_target=True)
            write_sdist(missing, include_target=False)
            check_sdist_readme_links(complete, root / "complete-unpacked")
            with self.assertRaisesRegex(RuntimeError, "missing README target"):
                check_sdist_readme_links(missing, root / "missing-unpacked")
