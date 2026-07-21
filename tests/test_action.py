from __future__ import annotations

import ast
import contextlib
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evidence_loop.action_runner import main, run_companion_action
from evidence_loop.errors import EvidenceLoopError, OutputError
from evidence_loop.schema import MAX_BYTES, MAX_ITEMS


ROOT = Path(__file__).resolve().parents[1]
AS_OF = "2026-12-31T00:00:00Z"


class CompanionActionTests(unittest.TestCase):
    def _workspace(self, root: Path, *, second: bool = True) -> Path:
        envelopes = root / "envelopes"
        envelopes.mkdir()
        (envelopes / "first.json").write_bytes((ROOT / "examples" / "connector-envelope.json").read_bytes())
        if second:
            (envelopes / "second.json").write_bytes(
                (ROOT / "examples" / "connector-envelope-second.json").read_bytes()
            )
        return envelopes

    def test_action_equivalent_run_is_offline_deterministic_and_exact(self):
        original_connect = socket.socket.connect
        original_create_connection = socket.create_connection

        def denied(*args, **kwargs):
            raise AssertionError("network call attempted")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._workspace(root)
            runner_temp = root / "runner-temp"
            runner_temp.mkdir()
            github_output = runner_temp / "github-output"
            github_output.touch()
            with mock.patch.object(socket.socket, "connect", denied), mock.patch.object(
                socket, "create_connection", denied
            ):
                first = run_companion_action(
                    workspace_value=str(root),
                    envelope_directory_value="envelopes",
                    as_of_value=AS_OF,
                    output_directory_value="artifacts",
                    runner_temp_value=str(runner_temp),
                    github_output_value=str(github_output),
                )
            self.assertIs(socket.socket.connect, original_connect)
            self.assertIs(socket.create_connection, original_create_connection)
            self.assertEqual(first["terminal_state"], "clean-no-op")
            self.assertEqual(first["external_calls"], 0)
            self.assertEqual(first["estimated_cost"], 0)
            self.assertEqual(first["input_count"], 2)
            artifacts = root / "artifacts"
            self.assertEqual(
                {path.name for path in artifacts.iterdir()},
                {"normalized.json", "run.json", "last-success.json"},
            )
            normalized = json.loads((artifacts / "normalized.json").read_text(encoding="utf-8"))
            receipt = json.loads((artifacts / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["input_digest"], normalized["input_digest"])
            self.assertEqual(receipt["receipt_sha256"], first["receipt_sha256"])
            self.assertEqual(receipt["safety"]["provider_access"], False)
            self.assertEqual(
                sorted(
                    evidence["provider_response_sha256"]
                    for site in receipt["sites"]
                    for evidence in site["evidence"]
                ),
                sorted(
                    json.loads(path.read_text(encoding="utf-8"))["provider_response_sha256"]
                    for path in (root / "envelopes").iterdir()
                ),
            )
            output_lines = dict(
                line.split("=", 1) for line in github_output.read_text(encoding="utf-8").splitlines()
            )
            self.assertEqual(output_lines["terminal-state"], "clean-no-op")
            self.assertEqual(output_lines["external-calls"], "0")
            self.assertEqual(output_lines["artifact-path"], str(artifacts))

            second_root = root / "repeat"
            second_root.mkdir()
            self._workspace(second_root)
            repeated = run_companion_action(
                workspace_value=str(second_root),
                envelope_directory_value="envelopes",
                as_of_value=AS_OF,
                output_directory_value="artifacts",
            )
            self.assertEqual(first["input_digest"], repeated["input_digest"])
            self.assertEqual(first["receipt_sha256"], repeated["receipt_sha256"])

    def test_action_cli_is_value_free_and_traceback_free(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._workspace(root, second=False)
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(
                    [
                        "--workspace",
                        str(root),
                        "--envelope-directory",
                        "envelopes",
                        "--as-of",
                        AS_OF,
                        "--output-directory",
                        "artifacts",
                    ]
                )
            self.assertEqual(code, 0)
            public_summary = json.loads(out.getvalue())
            self.assertEqual(public_summary["terminal_state"], "clean-no-op")
            self.assertNotIn("artifact_path", public_summary)
            self.assertNotIn(str(root), out.getvalue())
            self.assertEqual(err.getvalue(), "")

            hostile = root / "hostile"
            hostile.mkdir()
            marker = "api" + "_key=do-not-reflect"
            (hostile / "bad.json").write_text(json.dumps({"limitations": marker}), encoding="utf-8")
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(
                    [
                        "--workspace",
                        str(root),
                        "--envelope-directory",
                        "hostile",
                        "--as-of",
                        AS_OF,
                        "--output-directory",
                        "blocked-output",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertNotIn(marker, err.getvalue())
            self.assertNotIn("Traceback", err.getvalue())
            self.assertFalse((root / "blocked-output").exists())

    def test_paths_symlinks_and_ambiguous_configuration_fail_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            envelopes = self._workspace(root, second=False)
            outside = root / "outside.json"
            outside.write_bytes((ROOT / "examples" / "connector-envelope.json").read_bytes())
            link = envelopes / "linked.json"
            link.symlink_to(outside)
            cases = [
                {"envelope_directory_value": "../envelopes", "output_directory_value": "out-a"},
                {"envelope_directory_value": str(envelopes), "output_directory_value": "out-b"},
                {"envelope_directory_value": "envelopes", "output_directory_value": "envelopes/out"},
                {"envelope_directory_value": "envelopes", "output_directory_value": "envelopes"},
            ]
            for index, values in enumerate(cases):
                with self.subTest(index=index), self.assertRaises(EvidenceLoopError):
                    run_companion_action(
                        workspace_value=str(root),
                        as_of_value=AS_OF,
                        **values,
                    )
            link.unlink()
            output_link = root / "output-link"
            output_link.symlink_to(root / "target", target_is_directory=True)
            with self.assertRaises(EvidenceLoopError):
                run_companion_action(
                    workspace_value=str(root),
                    envelope_directory_value="envelopes",
                    as_of_value=AS_OF,
                    output_directory_value="output-link",
                )
            existing = root / "existing"
            existing.mkdir()
            with self.assertRaises(EvidenceLoopError):
                run_companion_action(
                    workspace_value=str(root),
                    envelope_directory_value="envelopes",
                    as_of_value=AS_OF,
                    output_directory_value="existing",
                )
            with self.assertRaises(EvidenceLoopError):
                run_companion_action(
                    workspace_value="/",
                    envelope_directory_value="tmp",
                    as_of_value=AS_OF,
                    output_directory_value="output",
                )

    def test_malformed_unsafe_digest_limits_and_metadata_fail_closed(self):
        unsafe_envelope = json.loads((ROOT / "examples" / "connector-envelope.json").read_text(encoding="utf-8"))
        unsafe_envelope["limitations"] = "api" + "_key=do-not-persist"
        mutations = {
            "malformed": b"{",
            "credential": json.dumps(unsafe_envelope).encode("utf-8"),
            "oversize": b"{" + b"x" * MAX_BYTES,
        }
        for name, payload in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                envelopes = root / "envelopes"
                envelopes.mkdir()
                (envelopes / "input.json").write_bytes(payload)
                with self.assertRaises(EvidenceLoopError):
                    run_companion_action(
                        workspace_value=str(root),
                        envelope_directory_value="envelopes",
                        as_of_value=AS_OF,
                        output_directory_value="output",
                    )
                self.assertFalse((root / "output").exists())

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            envelopes = self._workspace(root, second=False)
            envelope = json.loads((envelopes / "first.json").read_text(encoding="utf-8"))
            envelope["provider_response_sha256"] = "0" * 63
            (envelopes / "first.json").write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaises(EvidenceLoopError):
                run_companion_action(
                    workspace_value=str(root),
                    envelope_directory_value="envelopes",
                    as_of_value=AS_OF,
                    output_directory_value="output",
                )
            for path in list(envelopes.iterdir()):
                path.unlink()
            for index in range(MAX_ITEMS + 1):
                (envelopes / f"input-{index:03d}.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(EvidenceLoopError):
                run_companion_action(
                    workspace_value=str(root),
                    envelope_directory_value="envelopes",
                    as_of_value=AS_OF,
                    output_directory_value="output",
                )
            self.assertFalse((root / "output").exists())

            runner_temp = root / "runner-temp"
            runner_temp.mkdir()
            with self.assertRaises(EvidenceLoopError):
                run_companion_action(
                    workspace_value=str(root),
                    envelope_directory_value="envelopes",
                    as_of_value=AS_OF,
                    output_directory_value="output",
                    runner_temp_value=str(runner_temp),
                )
            github_output = runner_temp / "github-output"
            github_output.touch()
            outside_output = root / "outside-output"
            outside_output.touch()
            with self.assertRaises(EvidenceLoopError):
                run_companion_action(
                    workspace_value=str(root),
                    envelope_directory_value="envelopes",
                    as_of_value=AS_OF,
                    output_directory_value="output",
                    runner_temp_value=str(runner_temp),
                    github_output_value=str(outside_output),
                )
            hardlink_output = runner_temp / "hardlink-output"
            hardlink_output.hardlink_to(outside_output)
            with self.assertRaises(EvidenceLoopError):
                run_companion_action(
                    workspace_value=str(root),
                    envelope_directory_value="envelopes",
                    as_of_value=AS_OF,
                    output_directory_value="output",
                    runner_temp_value=str(runner_temp),
                    github_output_value=str(hardlink_output),
                )

    def test_receipt_digest_mismatch_is_rejected_before_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._workspace(root, second=False)
            fake_receipt = {
                "schema_version": "2",
                "terminal_state": "clean-no-op",
                "input_digest": "0" * 64,
                "receipt_sha256": "0" * 64,
                "summary": {"external_calls": 0, "estimated_cost": 0},
                "safety": {
                    "offline": True,
                    "site_mutation": False,
                    "provider_access": False,
                    "approval_boundary": "human-required",
                },
                "sites": [],
            }
            with mock.patch("evidence_loop.action_runner.execute", return_value=fake_receipt):
                with self.assertRaises(OutputError):
                    run_companion_action(
                        workspace_value=str(root),
                        envelope_directory_value="envelopes",
                        as_of_value=AS_OF,
                        output_directory_value="output",
                    )
            self.assertFalse((root / "output").exists())

    def test_action_metadata_is_pinned_and_shell_has_no_expression_interpolation(self):
        action = (ROOT / "action.yml").read_text(encoding="utf-8")
        uses = [
            line.split("uses:", 1)[1].strip().split(" ", 1)[0]
            for line in action.splitlines()
            if line.lstrip().startswith("uses:")
        ]
        self.assertEqual(
            uses,
            [
                "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
                "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
            ],
        )
        lines = action.splitlines()
        for index, line in enumerate(lines):
            if line.lstrip() != "run: |":
                continue
            indentation = len(line) - len(line.lstrip())
            block = []
            for following in lines[index + 1 :]:
                if following.strip() and len(following) - len(following.lstrip()) <= indentation:
                    break
                block.append(following)
            self.assertNotIn("${{", "\n".join(block))
        self.assertNotIn("secrets.", action)
        self.assertNotIn("curl ", action)
        self.assertNotIn("wget ", action)

        source = (ROOT / "src" / "evidence_loop" / "action_runner.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertTrue(
            imported.isdisjoint(
                {"http", "socket", "subprocess", "urllib", "requests", "httpx", "aiohttp", "selenium", "playwright"}
            )
        )
        self.assertNotIn("os.environ", source)
        self.assertNotIn("os.getenv", source)


if __name__ == "__main__":
    unittest.main()
