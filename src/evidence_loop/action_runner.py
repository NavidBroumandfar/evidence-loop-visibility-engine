"""Fail-closed companion GitHub Action boundary for sanitized envelopes."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from .engine import _atomic_write, execute, persist, receipt_digest
from .errors import EvidenceLoopError, InputError, OutputError, PathSafetyError
from .normalizer import load_envelope, normalize_envelopes, serialized_normalized_document
from .schema import MAX_BYTES, MAX_ITEMS, parse_utc_timestamp


SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SAFE_ENVELOPE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,123}\.json$")
TERMINAL_STATES = {"approval-required", "clean-no-op", "blocked"}
APPROVED_ARTIFACTS = {
    "approval-required": {"normalized.json", "run.json", "last-success.json"},
    "clean-no-op": {"normalized.json", "run.json", "last-success.json"},
    "blocked": {"normalized.json", "run.json"},
}
ALLOWED_SYSTEM_SYMLINKS = {Path("/tmp"), Path("/var")}


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise InputError("action-arguments", "companion Action arguments are incomplete or ambiguous")


def _reject_control_text(value: str, *, label: str) -> None:
    if not value or value != value.strip() or any(character in value for character in ("\x00", "\r", "\n")):
        raise PathSafetyError("action-path", f"{label} is not a safe path")


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        if current.is_symlink() and current not in ALLOWED_SYSTEM_SYMLINKS:
            raise PathSafetyError("symlink-path", "companion Action paths must not contain symlinks")


def _workspace_path(workspace_value: str) -> Path:
    _reject_control_text(workspace_value, label="workspace")
    raw = Path(workspace_value)
    if not raw.is_absolute() or ".." in raw.parts:
        raise PathSafetyError("action-workspace", "workspace must be an absolute safe directory")
    workspace = Path(os.path.abspath(raw))
    if workspace == Path(workspace.anchor):
        raise PathSafetyError("action-workspace", "filesystem root is not a safe workspace")
    _reject_symlink_components(workspace)
    if not workspace.exists() or not workspace.is_dir() or workspace.is_symlink():
        raise PathSafetyError("action-workspace", "workspace must be an existing regular directory")
    return workspace


def _relative_directory(workspace: Path, value: str, *, label: str, must_exist: bool) -> Path:
    _reject_control_text(value, label=label)
    if "\\" in value:
        raise PathSafetyError("action-path", f"{label} must use repository-relative POSIX components")
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} or not SAFE_COMPONENT_RE.fullmatch(part) for part in relative.parts
    ):
        raise PathSafetyError("action-path", f"{label} must be a bounded repository-relative directory")
    path = Path(os.path.abspath(workspace / relative))
    if not path.is_relative_to(workspace):
        raise PathSafetyError("path-traversal", f"{label} must remain inside the workspace")
    _reject_symlink_components(path)
    if must_exist and (not path.exists() or not path.is_dir() or path.is_symlink()):
        raise PathSafetyError("action-input", "envelope directory must be an existing regular directory")
    if not must_exist and path.exists():
        raise PathSafetyError("action-output", "Action output directory must not already exist")
    return path


def _envelope_paths(input_directory: Path) -> list[Path]:
    paths: list[Path] = []
    total_bytes = 0
    try:
        entries = input_directory.iterdir()
        for entry in entries:
            if len(paths) >= MAX_ITEMS:
                raise InputError("too-many-items", "envelope file count exceeds the public limit")
            if entry.is_symlink() or not SAFE_ENVELOPE_NAME_RE.fullmatch(entry.name):
                raise PathSafetyError("action-input", "envelope directory contains an unsupported entry")
            try:
                mode = entry.lstat().st_mode
                size = entry.lstat().st_size
            except OSError as exc:
                raise InputError("input-read", "envelope metadata could not be read") from exc
            if not stat.S_ISREG(mode):
                raise PathSafetyError("action-input", "envelope directory must contain regular JSON files only")
            total_bytes += size
            if size > MAX_BYTES or total_bytes > MAX_BYTES:
                raise InputError("input-too-large", "connector envelope set exceeds the 1 MB public boundary")
            paths.append(entry)
    except OSError as exc:
        raise InputError("input-read", "envelope directory could not be enumerated") from exc
    if not paths:
        raise InputError("envelopes", "envelope directory must contain at least one JSON file")
    return sorted(paths, key=lambda path: path.name)


def _load_envelopes(paths: list[Path]) -> list[dict[str, Any]]:
    envelopes: list[dict[str, Any]] = []
    total_bytes = 0
    for path in paths:
        envelope, raw = load_envelope(path)
        total_bytes += len(raw)
        if total_bytes > MAX_BYTES:
            raise InputError("input-too-large", "connector envelope set exceeds the 1 MB public boundary")
        envelopes.append(envelope)
    return envelopes


def _github_output_target(runner_temp_value: str | None, github_output_value: str | None) -> Path | None:
    if (runner_temp_value is None) != (github_output_value is None):
        raise PathSafetyError("action-metadata", "runner temp and GitHub output must be configured together")
    if runner_temp_value is None or github_output_value is None:
        return None
    runner_temp = _workspace_path(runner_temp_value)
    _reject_control_text(github_output_value, label="GitHub output")
    output = Path(github_output_value)
    if not output.is_absolute() or ".." in output.parts:
        raise PathSafetyError("action-metadata", "GitHub output must be an absolute runner-temp file")
    output = Path(os.path.abspath(output))
    _reject_symlink_components(output)
    if not output.is_relative_to(runner_temp) or output == runner_temp:
        raise PathSafetyError("action-metadata", "GitHub output must remain inside runner temp")
    if output.exists():
        try:
            output_stat = output.lstat()
        except OSError as exc:
            raise PathSafetyError("action-metadata", "GitHub output metadata could not be inspected") from exc
        if output.is_symlink() or not stat.S_ISREG(output_stat.st_mode) or output_stat.st_nlink != 1:
            raise PathSafetyError("action-metadata", "GitHub output must be a single-link regular file")
    if not output.parent.exists() or not output.parent.is_dir():
        raise PathSafetyError("action-metadata", "GitHub output parent must exist")
    return output


def _validate_receipt(
    receipt: dict[str, Any],
    document: dict[str, Any],
    envelopes: list[dict[str, Any]],
) -> None:
    terminal_state = receipt.get("terminal_state")
    if terminal_state not in TERMINAL_STATES:
        raise OutputError("action-receipt", "core receipt has an unsupported terminal state")
    if receipt.get("schema_version") != "2" or receipt.get("input_digest") != document["input_digest"]:
        raise OutputError("action-receipt", "core receipt digest binding failed")
    if receipt.get("receipt_sha256") != receipt_digest(receipt):
        raise OutputError("action-receipt", "core receipt integrity check failed")
    summary = receipt.get("summary")
    safety = receipt.get("safety")
    if not isinstance(summary, dict) or summary.get("external_calls") != 0 or summary.get("estimated_cost") != 0:
        raise OutputError("action-receipt", "core receipt external-call boundary failed")
    if safety != {
        "offline": True,
        "site_mutation": False,
        "provider_access": False,
        "approval_boundary": "human-required",
    }:
        raise OutputError("action-receipt", "core receipt safety boundary failed")
    expected_digests = sorted(envelope["provider_response_sha256"] for envelope in envelopes)
    receipt_digests = sorted(
        evidence["provider_response_sha256"]
        for site in receipt.get("sites", [])
        for evidence in site.get("evidence", [])
    )
    if receipt_digests != expected_digests:
        raise OutputError("action-receipt", "provider-response digest preservation failed")


def _write_github_outputs(path: Path, summary: dict[str, Any]) -> None:
    values = {
        "terminal-state": summary["terminal_state"],
        "artifact-path": summary["artifact_path"],
        "input-digest": summary["input_digest"],
        "receipt-sha256": summary["receipt_sha256"],
        "external-calls": "0",
    }
    if any(not isinstance(value, str) or any(character in value for character in ("\r", "\n")) for value in values.values()):
        raise OutputError("action-metadata", "GitHub output values are outside the safe boundary")
    try:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            for name, value in values.items():
                handle.write(f"{name}={value}\n")
    except OSError as exc:
        raise OutputError("action-metadata", "GitHub output metadata could not be written") from exc


def run_companion_action(
    *,
    workspace_value: str,
    envelope_directory_value: str,
    as_of_value: str,
    output_directory_value: str,
    runner_temp_value: str | None = None,
    github_output_value: str | None = None,
) -> dict[str, Any]:
    """Normalize sanitized envelopes, execute once, and persist approved files."""
    workspace = _workspace_path(workspace_value)
    input_directory = _relative_directory(
        workspace, envelope_directory_value, label="envelope directory", must_exist=True
    )
    output_directory = _relative_directory(
        workspace, output_directory_value, label="output directory", must_exist=False
    )
    if (
        input_directory == output_directory
        or input_directory in output_directory.parents
        or output_directory in input_directory.parents
    ):
        raise PathSafetyError("action-path", "input and output directories must not overlap")
    github_output = _github_output_target(runner_temp_value, github_output_value)
    as_of = parse_utc_timestamp(as_of_value, label="as_of")
    paths = _envelope_paths(input_directory)
    envelopes = _load_envelopes(paths)
    document = normalize_envelopes(envelopes, as_of)
    normalized_payload = serialized_normalized_document(document)
    receipt = execute(normalized_payload)
    _validate_receipt(receipt, document, envelopes)

    try:
        output_directory.mkdir(parents=True)
    except OSError as exc:
        raise OutputError("action-output", "Action output directory could not be created") from exc
    _atomic_write(output_directory / "normalized.json", normalized_payload)
    persist(receipt, output_directory)
    actual = {path.name for path in output_directory.iterdir()}
    expected = APPROVED_ARTIFACTS[receipt["terminal_state"]]
    if actual != expected or any(path.is_symlink() or not path.is_file() for path in output_directory.iterdir()):
        raise OutputError("action-artifacts", "Action output contains an unapproved artifact surface")

    summary = {
        "schema_version": "2",
        "terminal_state": receipt["terminal_state"],
        "input_count": len(envelopes),
        "site_count": len(document["sites"]),
        "evidence_count": sum(len(site["evidence"]) for site in document["sites"]),
        "input_digest": document["input_digest"],
        "receipt_sha256": receipt["receipt_sha256"],
        "artifact_path": str(output_directory),
        "external_calls": 0,
        "estimated_cost": 0,
    }
    if github_output is not None:
        _write_github_outputs(github_output, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(prog="evidence-loop-action", add_help=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--envelope-directory", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--runner-temp")
    parser.add_argument("--github-output")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        summary = run_companion_action(
            workspace_value=args.workspace,
            envelope_directory_value=args.envelope_directory,
            as_of_value=args.as_of,
            output_directory_value=args.output_directory,
            runner_temp_value=args.runner_temp,
            github_output_value=args.github_output,
        )
        public_summary = {key: value for key, value in summary.items() if key != "artifact_path"}
        print(json.dumps(public_summary, sort_keys=True))
        return 0
    except EvidenceLoopError as exc:
        print(
            json.dumps({"valid": False, "error_code": exc.code, "message": exc.message}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    except Exception:
        print(
            json.dumps(
                {"valid": False, "error_code": "action-internal", "message": "companion Action failed closed"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
