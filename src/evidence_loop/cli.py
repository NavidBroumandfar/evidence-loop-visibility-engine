"""Command line interface with value-free summaries."""

from __future__ import annotations

import argparse
import importlib.resources as resources
import json
import sys
from pathlib import Path

from . import __version__
from .engine import execute, persist
from .errors import EvidenceLoopError
from .schema import load_document


def _summary(receipt: dict[str, object]) -> dict[str, object]:
    return {
        "run_id": receipt.get("run_id"),
        "terminal_state": receipt.get("terminal_state"),
        "site_count": receipt.get("summary", {}).get("site_count"),
        "accepted_site_count": receipt.get("summary", {}).get("accepted_site_count"),
        "blocked_site_count": receipt.get("summary", {}).get("blocked_site_count"),
        "proposal_count": receipt.get("summary", {}).get("proposal_count"),
        "external_calls": 0,
        "estimated_cost": 0,
    }


def _cmd_validate(args: argparse.Namespace) -> int:
    document, _, _ = load_document(args.input)
    print(json.dumps({"valid": True, "schema_version": document["schema_version"], "site_count": len(document["sites"])}, sort_keys=True))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    _, raw, _ = load_document(args.input)
    receipt = execute(raw)
    persist(receipt, args.output)
    print(json.dumps(_summary(receipt), sort_keys=True))
    return 3 if receipt["terminal_state"] == "blocked" else 0


def _resource_bytes(name: str) -> bytes:
    return resources.files("evidence_loop.resources").joinpath(name).read_bytes()


def _cmd_demo(args: argparse.Namespace) -> int:
    names = ["normal", "clean-no-op", "contained-site-failure"]
    results = []
    output = Path(args.output)
    for name in names:
        raw = _resource_bytes(f"{name}.json")
        receipt = execute(raw)
        persist(receipt, output / name)
        results.append(_summary(receipt))
    print(json.dumps({"version": __version__, "demo_count": len(results), "runs": results, "external_calls": 0, "estimated_cost": 0}, sort_keys=True))
    return 0


def _cmd_benchmark(_: argparse.Namespace) -> int:
    cases = json.loads(_resource_bytes("benchmark.json"))
    passed = 0
    for case in cases["cases"]:
        raw = _resource_bytes(case["input"])
        receipt = execute(raw)
        expected = case["expected"]
        selected = {item["site_id"]: item["selected_opportunity_id"] for item in receipt["sites"]}
        if receipt["terminal_state"] == expected["terminal_state"] and selected == expected["selected"]:
            passed += 1
    total = len(cases["cases"])
    print(json.dumps({"suite": "deterministic-public-conformance-v1", "passed": passed, "total": total, "pass_rate": passed / total if total else 1.0, "external_calls": 0, "estimated_cost": 0}, sort_keys=True))
    return 0 if passed == total else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evidence-loop", description="Bounded evidence-first visibility loop")
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="validate a strict evidence input")
    validate.add_argument("--input", required=True)
    validate.set_defaults(func=_cmd_validate)
    run = sub.add_parser("run", help="run one bounded offline cycle")
    run.add_argument("--input", required=True)
    run.add_argument("--output", required=True)
    run.set_defaults(func=_cmd_run)
    demo = sub.add_parser("demo", help="run committed synthetic examples")
    demo.add_argument("--output", required=True)
    demo.set_defaults(func=_cmd_demo)
    benchmark = sub.add_parser("benchmark", help="run deterministic public conformance cases")
    benchmark.set_defaults(func=_cmd_benchmark)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.func(args))
    except EvidenceLoopError as exc:
        print(json.dumps({"valid": False, "error_code": exc.code, "message": exc.message}, sort_keys=True), file=sys.stderr)
        return 2
    except OSError:
        print(json.dumps({"valid": False, "error_code": "io", "message": "filesystem operation failed"}, sort_keys=True), file=sys.stderr)
        return 2
