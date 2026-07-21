"""Deterministic, offline Connector Exchange Envelope v1 normalization."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import InputError
from .schema import (
    MAX_BYTES,
    EVIDENCE_ID_DIGEST_CHARS,
    MAX_ITEMS,
    MAX_TEXT,
    SHA256_RE,
    _id,
    _json_loads,
    _require_keys,
    _slug,
    _validate_lineage,
    _validate_measure_map,
    _validate_window,
    _walk_limits,
    _walk_safety,
    canonical_json,
    canonical_public_origin,
    connector_evidence_id_from_identity,
    connector_evidence_identity,
    parse_utc_timestamp,
    safe_path,
    validate_document,
)

ENVELOPE_VERSION = "1"
ENVELOPE_REQUIRED = {
    "schema_version",
    "source",
    "provider",
    "scope_ref",
    "site_id",
    "site_url",
    "collected_at",
    "grain",
    "completeness",
    "freshness",
    "uncertainty",
    "measures",
    "lineage",
    "provider_response_sha256",
}
ENVELOPE_OPTIONAL = {"observation_window", "comparison_window", "limitations"}


def serialized_normalized_document(document: dict[str, Any]) -> bytes:
    """Return the exact compact CLI payload within the public byte boundary."""
    payload = canonical_json(document) + b"\n"
    if len(payload) > MAX_BYTES:
        raise InputError("output-too-large", "normalized output exceeds the 1 MB public boundary")
    return payload


def _validate_as_of(as_of: Any) -> datetime:
    if not isinstance(as_of, datetime) or as_of.tzinfo is not timezone.utc:
        raise InputError("as-of", "as_of must be an explicit UTC datetime")
    return as_of


def validate_envelope(envelope: Any) -> dict[str, Any]:
    """Validate one credential-free Connector Exchange Envelope v1 object."""
    if not isinstance(envelope, dict):
        raise InputError("invalid-root", "connector envelope root must be an object")
    _require_keys(envelope, ENVELOPE_REQUIRED | ENVELOPE_OPTIONAL, ENVELOPE_REQUIRED, "connector envelope")
    if envelope["schema_version"] != ENVELOPE_VERSION:
        raise InputError("schema-version", "unsupported connector envelope version")
    _slug(envelope["source"], "source")
    _slug(envelope["provider"], "provider")
    _id(envelope["scope_ref"], "scope_ref")
    _slug(envelope["site_id"], "site_id")
    canonical_url = canonical_public_origin(envelope["site_url"])
    collected_at = parse_utc_timestamp(envelope["collected_at"], label="collected_at")
    _slug(envelope["grain"], "grain")
    if envelope["completeness"] not in {"complete", "partial", "unknown"}:
        raise InputError("evidence-state", "completeness is outside the connector enum")
    if envelope["freshness"] not in {"fresh", "stale", "unknown"}:
        raise InputError("evidence-state", "freshness is outside the connector enum")
    if envelope["uncertainty"] not in {"low", "medium", "high", "unknown"}:
        raise InputError("evidence-state", "uncertainty is outside the connector enum")
    _validate_measure_map(envelope["measures"])
    _validate_lineage(envelope["lineage"])
    digest = envelope["provider_response_sha256"]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise InputError("digest", "provider_response_sha256 must be lowercase SHA-256")

    observation: tuple[str, str] | None = None
    if "observation_window" in envelope:
        observation = _validate_window(envelope["observation_window"], label="observation_window")
        if parse_utc_timestamp(observation[1], label="observation_window.end") > collected_at:
            raise InputError("window", "observation window must end by collected_at")
    if "comparison_window" in envelope:
        comparison = _validate_window(envelope["comparison_window"], label="comparison_window")
        if parse_utc_timestamp(comparison[1], label="comparison_window.end") > collected_at:
            raise InputError("window", "comparison window must end by collected_at")
        if observation is not None and parse_utc_timestamp(comparison[1], label="comparison_window.end") > parse_utc_timestamp(observation[0], label="observation_window.start"):
            raise InputError("window", "comparison window must end before observation window")
    if "limitations" in envelope and (
        not isinstance(envelope["limitations"], str)
        or not envelope["limitations"].strip()
        or len(envelope["limitations"]) > MAX_TEXT
    ):
        raise InputError("limitations", "limitations must be non-empty bounded text")
    _walk_limits(envelope)
    _walk_safety(envelope, allowed_digest_paths={("provider_response_sha256",)})
    normalized = dict(envelope)
    normalized["site_url"] = canonical_url
    return normalized


def parse_envelope_bytes(raw: bytes) -> dict[str, Any]:
    """Parse and validate one immutable envelope byte stream."""
    if not isinstance(raw, bytes):
        raise InputError("input-bytes", "connector envelope input must be immutable bytes")
    if len(raw) > MAX_BYTES:
        raise InputError("input-too-large", "connector envelope exceeds the 1 MB public boundary")
    return validate_envelope(_json_loads(raw))


def load_envelope(path_value: str | Path) -> tuple[dict[str, Any], bytes]:
    """Read exactly one safe envelope file for the CLI boundary."""
    path = safe_path(path_value)
    if not path.exists() or not path.is_file():
        raise InputError("input-path", "connector envelope input file does not exist")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError("input-read", "connector envelope input file could not be read") from exc
    return parse_envelope_bytes(raw), raw


def _identity(envelope: dict[str, Any]) -> dict[str, Any]:
    return connector_evidence_identity(
        source_kind=envelope["source"],
        provider=envelope["provider"],
        scope_ref=envelope["scope_ref"],
        site_id=envelope["site_id"],
        site_url=envelope["site_url"],
        observation_window=envelope.get("observation_window"),
        comparison_window=envelope.get("comparison_window"),
        observed_at=envelope["collected_at"],
        grain=envelope["grain"],
    )


def _evidence_id(identity: dict[str, Any]) -> str:
    return connector_evidence_id_from_identity(identity)


def _normalized_evidence(envelope: dict[str, Any], evidence_id: str) -> dict[str, Any]:
    facts: dict[str, Any] = {
        "provider": envelope["provider"],
        "scope_ref": envelope["scope_ref"],
        "grain": envelope["grain"],
        "measures": envelope["measures"],
    }
    for name in ("observation_window", "comparison_window", "limitations"):
        if name in envelope:
            facts[name] = envelope[name]
    return {
        "evidence_id": evidence_id,
        "source_kind": envelope["source"],
        "observed_at": envelope["collected_at"],
        "completeness": envelope["completeness"],
        "freshness": envelope["freshness"],
        "uncertainty": envelope["uncertainty"],
        "facts": facts,
        "lineage": [dict(item) for item in envelope["lineage"]],
        "provider_response_sha256": envelope["provider_response_sha256"],
    }


def normalize_envelopes(envelopes: Sequence[dict[str, Any]], as_of: datetime) -> dict[str, Any]:
    """Normalize a bounded set of envelopes into one schema-v2 core document."""
    if not isinstance(envelopes, Sequence) or isinstance(envelopes, (str, bytes, bytearray)) or not envelopes or len(envelopes) > MAX_ITEMS:
        raise InputError("envelopes", "envelopes must be a non-empty bounded sequence")
    if len(canonical_json(list(envelopes))) > MAX_BYTES:
        raise InputError("input-too-large", "connector envelope set exceeds the 1 MB public boundary")
    as_of_utc = _validate_as_of(as_of)
    grouped: dict[str, dict[str, Any]] = {}
    seen_tuples: set[bytes] = set()
    seen_ids: dict[str, bytes] = {}
    for candidate in envelopes:
        envelope = validate_envelope(candidate)
        if parse_utc_timestamp(envelope["collected_at"], label="collected_at") > as_of_utc:
            raise InputError("future-evidence", "collected_at must not be after as_of")
        site_id = envelope["site_id"]
        site_url = envelope["site_url"]
        existing = grouped.get(site_id)
        if existing is not None and existing["site"] != site_url:
            raise InputError("site-conflict", "site_id must map to exactly one canonical site URL")
        if existing is None:
            existing = {"site_id": site_id, "site": site_url, "evidence": [], "opportunities": []}
            grouped[site_id] = existing
        identity = _identity(envelope)
        identity_bytes = canonical_json(identity)
        if identity_bytes in seen_tuples:
            raise InputError("duplicate-evidence", "connector evidence identity must be unique")
        seen_tuples.add(identity_bytes)
        evidence_id = _evidence_id(identity)
        prior = seen_ids.get(evidence_id)
        if prior is not None and prior != identity_bytes:
            raise InputError("evidence-id-collision", "connector evidence identifier collision")
        seen_ids[evidence_id] = identity_bytes
        existing["evidence"].append(_normalized_evidence(envelope, evidence_id))

    sites = sorted(grouped.values(), key=lambda site: (site["site_id"], site["site"]))
    for site in sites:
        site["evidence"].sort(key=lambda evidence: evidence["evidence_id"])
    document: dict[str, Any] = {"schema_version": "2", "sites": sites}
    document["input_digest"] = hashlib.sha256(canonical_json(document)).hexdigest()
    document = validate_document(document)
    serialized_normalized_document(document)
    return document
