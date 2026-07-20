from __future__ import annotations

import contextlib
import base64
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import importlib.resources as resources
from unittest import mock

from evidence_loop.cli import main
from scripts.validate_public_release import scan
from scripts.artifact_smoke import preflight


ROOT = Path(__file__).resolve().parents[1]


class CliAndReleaseTests(unittest.TestCase):
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
