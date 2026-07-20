"""Observe -> Choose -> Act(proposal) -> Verify -> Record loop."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .capabilities import route
from .errors import EvidenceLoopError, OutputError, PathSafetyError
from .schema import canonical_json, parse_document_bytes, safe_path


def _eligible(opportunity: dict[str, Any], evidence_by_id: dict[str, dict[str, Any]]) -> bool:
    if route(opportunity["domain"]) is None:
        return False
    refs = [evidence_by_id[eid] for eid in opportunity["evidence_ids"]]
    # Freshness is a hard gate. Partial evidence can support a proposal, but
    # missing evidence cannot.
    return all(item["freshness"] == "fresh" and item["completeness"] != "missing" for item in refs)


def _choose(site: dict[str, Any]) -> dict[str, Any] | None:
    evidence_by_id = {item["evidence_id"]: item for item in site["evidence"]}
    candidates = [item for item in site["opportunities"] if _eligible(item, evidence_by_id)]
    if not candidates:
        return None
    # Lower priority wins; ties are deterministic and independent of input
    # ordering so a fresh observation can change the next choice.
    return sorted(candidates, key=lambda item: (item["priority"], item["opportunity_id"]))[0]


def _proposal(site: dict[str, Any], opportunity: dict[str, Any]) -> dict[str, Any]:
    capability = route(opportunity["domain"])
    if capability is None:
        raise ValueError("unsupported capability")
    return {
        "proposal_id": f"proposal-{opportunity['opportunity_id']}",
        "site_id": site["site_id"],
        "opportunity_id": opportunity["opportunity_id"],
        "evidence_ids": list(opportunity["evidence_ids"]),
        "capability": {"key": capability.key, "version": capability.version, "maturity": capability.maturity},
        "plan": capability.plan,
        "approval_gate": opportunity["approval_gate"],
        "approval_required": True,
        "mutation_allowed": False,
    }


def _verify_proposal(site: dict[str, Any], opportunity: dict[str, Any], proposal: Any) -> tuple[bool, str | None]:
    """Verify the proposal independently before it can enter a receipt."""
    capability = route(opportunity["domain"])
    if capability is None or not isinstance(proposal, dict):
        return False, "proposal-verification-failed"
    expected = {
        "proposal_id": f"proposal-{opportunity['opportunity_id']}",
        "site_id": site["site_id"],
        "opportunity_id": opportunity["opportunity_id"],
        "evidence_ids": list(opportunity["evidence_ids"]),
        "capability": {"key": capability.key, "version": capability.version, "maturity": capability.maturity},
        "plan": capability.plan,
        "approval_gate": opportunity["approval_gate"],
        "approval_required": True,
        "mutation_allowed": False,
    }
    # Equality over the complete safe object catches tampering, missing
    # lineage, routed-version drift, and truthy-but-not-bool approval flags.
    if proposal != expected:
        return False, "proposal-verification-failed"
    if proposal["site_id"] != site["site_id"] or proposal["opportunity_id"] != opportunity["opportunity_id"]:
        return False, "proposal-verification-failed"
    if proposal["evidence_ids"] != list(opportunity["evidence_ids"]):
        return False, "proposal-verification-failed"
    if proposal["approval_required"] is not True or proposal["mutation_allowed"] is not False:
        return False, "proposal-verification-failed"
    return True, None


def receipt_digest(receipt: dict[str, Any]) -> str:
    """Return the exact receipt digest over the canonical body without itself."""
    body = dict(receipt)
    body.pop("receipt_sha256", None)
    return hashlib.sha256(canonical_json(body)).hexdigest()


def execute(raw: bytes) -> dict[str, Any]:
    """Execute exactly the supplied raw bytes; parse and hash inside the boundary."""
    document = parse_document_bytes(raw)
    input_sha256 = hashlib.sha256(raw).hexdigest()
    site_results: list[dict[str, Any]] = []
    for site in document["sites"]:
        try:
            unknown = [item for item in site["opportunities"] if route(item["domain"]) is None]
            # An unknown capability poisons the complete site lane. It cannot
            # be bypassed by selecting a supported sibling opportunity.
            selected = None if unknown else _choose(site)
            if unknown:
                site_status = "blocked"
                blocked_reason = "unsupported-capability"
                proposal = None
                selected_id = None
            elif selected is None:
                site_status = "clean-no-op"
                blocked_reason = None
                proposal = None
                selected_id = None
            else:
                candidate = _proposal(site, selected)
                verified, reason = _verify_proposal(site, selected, candidate)
                if not verified:
                    site_status = "blocked"
                    blocked_reason = reason
                    proposal = None
                    selected_id = None
                else:
                    site_status = "approval-required"
                    blocked_reason = None
                    proposal = candidate
                    selected_id = selected["opportunity_id"]
            if site_status in {"clean-no-op", "blocked"}:
                site_results.append(
                    {
                        "site_id": site["site_id"],
                        "evidence": [
                            {key: item[key] for key in ("evidence_id", "source_kind", "observed_at", "completeness", "freshness", "uncertainty")}
                            for item in site["evidence"]
                        ],
                        "status": site_status,
                        "selected_opportunity_id": selected_id,
                        "blocked_reason": blocked_reason,
                        "proposal": proposal,
                    }
                )
            else:
                site_results.append(
                    {
                        "site_id": site["site_id"],
                        "evidence": [
                            {key: item[key] for key in ("evidence_id", "source_kind", "observed_at", "completeness", "freshness", "uncertainty")}
                            for item in site["evidence"]
                        ],
                        "status": "approval-required",
                        "selected_opportunity_id": selected_id,
                        "blocked_reason": None,
                        "proposal": proposal,
                    }
                )
        except Exception:
            # A malformed site lane is contained; global validation has already
            # rejected unsafe structure before this point.
            site_results.append(
                {"site_id": site.get("site_id", "unknown"), "evidence": [], "status": "blocked", "selected_opportunity_id": None, "blocked_reason": "site-lane-error", "proposal": None}
            )
    accepted = sum(1 for item in site_results if item["status"] == "approval-required")
    blocked = sum(1 for item in site_results if item["status"] == "blocked")
    if accepted:
        terminal = "approval-required"
    elif blocked:
        terminal = "blocked"
    else:
        terminal = "clean-no-op"
    run_id = document.get("run_id") or f"run-{input_sha256[:12]}"
    receipt: dict[str, Any] = {
        "schema_version": "1",
        "run_id": run_id,
        "terminal_state": terminal,
        "input_sha256": input_sha256,
        "sites": site_results,
        "summary": {
            "site_count": len(site_results),
            "accepted_site_count": accepted,
            "blocked_site_count": blocked,
            "proposal_count": accepted,
            "external_calls": 0,
            "estimated_cost": 0,
        },
        "safety": {
            "offline": True,
            "site_mutation": False,
            "provider_access": False,
            "approval_boundary": "human-required",
        },
    }
    receipt["receipt_sha256"] = receipt_digest(receipt)
    return receipt


def _reject_output_children(path: Path) -> None:
    if not path.exists():
        return
    for child in path.rglob("*"):
        if child.is_symlink():
            raise PathSafetyError("symlink-output", "output tree contains a symlink")


def _atomic_write(path: Path, payload: bytes) -> None:
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise OutputError("output-write", "atomic output write failed") from exc


def persist(receipt: dict[str, Any], output_value: str | os.PathLike[str]) -> Path:
    output = safe_path(output_value, output=True)
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise PathSafetyError("symlink-output", "output directory must not be a symlink")
    _reject_output_children(output)
    payload = json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    run_path = output / "run.json"
    _atomic_write(run_path, payload.encode("utf-8"))
    if receipt["terminal_state"] != "blocked":
        _atomic_write(output / "last-success.json", payload.encode("utf-8"))
    return run_path
