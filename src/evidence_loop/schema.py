"""Strict, offline input handling and public safety checks.

The parser intentionally accepts a small schema. It rejects duplicate JSON
keys and unsafe strings before any planning or output path is touched. Schema
version 2 adds the clean-room connector-normalized evidence shape without
changing the schema version 1 contract.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import InputError, PathSafetyError

MAX_BYTES = 1024 * 1024
MAX_DEPTH = 8
MAX_ITEMS = 200
MAX_TEXT = 512
MAX_NUMBER_TEXT = 256
MIN_BASE64_TEXT = 12
SCHEMA_VERSION = "1"
SCHEMA_V2 = "2"

ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]{0,63}$")
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
EVIDENCE_ID_RE = re.compile(r"^ev-[a-z2-7]{8,52}$")
EVIDENCE_ID_DIGEST_CHARS = 20
PRIVATE_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])/(?:Users|home|private|var/folders|var/log|etc|root|tmp|usr|opt|Library/Application Support|System|Volumes)(?:/|$)"
)
FILE_URI_RE = re.compile(r"(?i)\b" + "file" + r":(?://|/)")
WINDOWS_DRIVE_PRIVATE_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]+(?:Users|Windows|ProgramData|Program Files|Documents and Settings)(?:[\\/]+|$)"
)
WINDOWS_UNC_PRIVATE_PATH_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9:])[\\/]{2}[^\\/\s]+[\\/]+(?:[^\\/\s]+[\\/]+)?(?:Users|Windows|ProgramData|Program Files|Documents and Settings)(?:[\\/]+|$)"
)
ASSIGNMENT_RE = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|auth(?:entication)?[_ -]?token|secret|password|private[_ -]?key|bearer)\s*[:=]"
)
TOKEN_RE = re.compile(r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~-]{16,}\b")
JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
PROVIDER_TOKEN_RE = re.compile(r"(?i)(?:xox[baprs]-[A-Za-z0-9-]{10,}|vpat_[A-Za-z0-9]{10,}|vercel_[A-Za-z0-9]{10,})")
HEX64_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
SECRET_KEY_RE = re.compile(r"(?i)^(?:api[_ -]?key|access[_ -]?token|auth(?:entication)?[_ -]?token|token|secret|password|private[_ -]?key)$")
PRIVATE_IDENTIFIER_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:"
    r"(?:provider|property|project|team|account|tenant|workspace|organization|org|user)[_-]id"
    r"|(?:properties|property|provider|project|team|account|tenant|workspace|organization|org|user)-[0-9]{3,}"
    r"|(?:provider|property|properties|project|team|account|tenant|workspace|organization|org|user|uid|session|prj|dpl|acct|usr)_[A-Za-z0-9][A-Za-z0-9_-]{5,63}"
    r")(?![A-Za-z0-9_-])"
)
UUID_RE = re.compile(
    r"(?i)(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])"
)
MAX_BASE64_DECODE_DEPTH = 4

ALLOWED_TOP = {"schema_version", "run_id", "input_digest", "sites"}
ALLOWED_SITE = {"site_id", "site", "evidence", "opportunities"}
ALLOWED_EVIDENCE_V1 = {
    "evidence_id",
    "source_kind",
    "observed_at",
    "completeness",
    "freshness",
    "uncertainty",
    "summary",
    "facts",
}
ALLOWED_EVIDENCE_V2 = {
    "evidence_id",
    "source_kind",
    "observed_at",
    "completeness",
    "freshness",
    "uncertainty",
    "facts",
    "lineage",
    "provider_response_sha256",
}
ALLOWED_FACTS_V2 = {
    "provider",
    "scope_ref",
    "grain",
    "observation_window",
    "comparison_window",
    "limitations",
    "measures",
}
ALLOWED_OPPORTUNITY = {
    "opportunity_id",
    "domain",
    "title",
    "priority",
    "evidence_ids",
    "approval_gate",
    "constraint",
}

FRESHNESS = {"fresh", "stale", "expired"}
COMPLETENESS = {"complete", "partial", "missing"}
UNCERTAINTY = {"low", "medium", "high"}
FRESHNESS_V2 = FRESHNESS | {"unknown"}
COMPLETENESS_V2 = COMPLETENESS | {"unknown"}
UNCERTAINTY_V2 = UNCERTAINTY | {"unknown"}


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate-key", "JSON object contains duplicate keys")
        result[key] = value
    return result


def _json_loads(raw: bytes) -> Any:
    def bounded_int(value: str) -> int:
        if len(value) > MAX_NUMBER_TEXT:
            raise InputError("number-too-large", "numeric token exceeds the public limit")
        try:
            return int(value)
        except ValueError as exc:
            raise InputError("invalid-number", "numeric token is invalid") from exc

    def bounded_float(value: str) -> float:
        if len(value) > MAX_NUMBER_TEXT:
            raise InputError("number-too-large", "numeric token exceeds the public limit")
        try:
            parsed = float(value)
        except ValueError as exc:
            raise InputError("invalid-number", "numeric token is invalid") from exc
        if not math.isfinite(parsed):
            raise InputError("non-finite-number", "NaN and Infinity are not accepted")
        return parsed

    def reject_constant(_: str) -> Any:
        raise InputError("non-finite-number", "NaN and Infinity are not accepted")

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_int=bounded_int,
            parse_float=bounded_float,
            parse_constant=reject_constant,
        )
    except UnicodeDecodeError as exc:
        raise InputError("invalid-encoding", "input must be UTF-8 JSON") from exc
    except InputError:
        raise
    except json.JSONDecodeError as exc:
        raise InputError("invalid-json", "input is not valid JSON") from exc
    except (RecursionError, ValueError) as exc:
        raise InputError("invalid-json", "input JSON is outside the safe parser boundary") from exc


def _walk_limits(value: Any) -> None:
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise InputError("too-deep", "input nesting exceeds public limit")
        if isinstance(current, dict):
            if len(current) > MAX_ITEMS:
                raise InputError("too-many-items", "object contains too many items")
            for key, child in current.items():
                if not isinstance(key, str) or len(key) > MAX_TEXT:
                    raise InputError("oversize-text", "object key exceeds public limit")
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            if len(current) > MAX_ITEMS:
                raise InputError("too-many-items", "array contains too many items")
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, str) and len(current) > MAX_TEXT:
            raise InputError("oversize-text", "text exceeds public limit")
        elif isinstance(current, float) and not math.isfinite(current):
            raise InputError("non-finite-number", "NaN and Infinity are not accepted")


def _decode_base64_text(value: str) -> str | None:
    if len(value) < MIN_BASE64_TEXT or len(value) > MAX_TEXT or not re.fullmatch(r"[A-Za-z0-9_+/=-]+", value):
        return None
    padded = value + "=" * (-len(value) % 4)
    try:
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        return raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


def _base64_decoded(value: str) -> list[str]:
    """Decode bounded nested standard or URL-safe Base64 text fail-closed."""
    decoded_text: list[str] = []
    candidate = value
    for _ in range(MAX_BASE64_DECODE_DEPTH):
        decoded = _decode_base64_text(candidate)
        if decoded is None:
            break
        decoded_text.append(decoded)
        candidate = decoded
    else:
        if _decode_base64_text(candidate) is not None:
            raise InputError("unsafe-string", "input contains excessive wrapped material")
    return decoded_text


def _unsafe_text(value: str) -> bool:
    return bool(
        PRIVATE_PATH_RE.search(value)
        or FILE_URI_RE.search(value)
        or WINDOWS_DRIVE_PRIVATE_PATH_RE.search(value)
        or WINDOWS_UNC_PRIVATE_PATH_RE.search(value)
        or ASSIGNMENT_RE.search(value)
        or TOKEN_RE.search(value)
        or BEARER_TOKEN_RE.search(value)
        or JWT_RE.search(value)
        or PROVIDER_TOKEN_RE.search(value)
        or PRIVATE_IDENTIFIER_RE.search(value)
        or UUID_RE.search(value)
        or "BEGIN PRIVATE KEY" in value.upper()
    )


def _scan_text(value: str) -> None:
    if _unsafe_text(value):
        raise InputError("unsafe-string", "input contains a private path or credential marker")
    if HEX64_RE.search(value.lower()):
        raise InputError("unsafe-string", "input contains a token-like digest marker")
    for decoded in _base64_decoded(value):
        if _unsafe_text(decoded) or HEX64_RE.search(decoded.lower()):
            raise InputError("unsafe-string", "input contains a wrapped credential marker")


def _walk_safety(value: Any, *, allowed_digest_paths: set[tuple[Any, ...]] | None = None) -> None:
    allowed = allowed_digest_paths or set()
    stack: list[tuple[Any, tuple[Any, ...]]] = [(value, ())]
    while stack:
        current, path = stack.pop()
        if isinstance(current, dict):
            for child_key, child in current.items():
                child_path = path + (child_key,)
                if child_path not in allowed:
                    if child_key in {"input_digest", "provider_response_sha256"}:
                        raise InputError("unsafe-string", "digest fields are allowed only at their exact schema paths")
                    _scan_text(child_key)
                if SECRET_KEY_RE.fullmatch(child_key):
                    raise InputError("unsafe-string", "input contains a credential-like field")
                stack.append((child, child_path))
        elif isinstance(current, list):
            stack.extend((child, path + (index,)) for index, child in enumerate(current))
        elif isinstance(current, str) and path not in allowed:
            if not (path and path[-1] == "reference" and current == "provider_response_sha256"):
                _scan_text(current)


def _require_keys(obj: dict[str, Any], allowed: set[str], required: set[str], label: str) -> None:
    unknown = set(obj) - allowed
    if unknown:
        raise InputError("unknown-field", f"{label} contains unsupported fields")
    missing = required - set(obj)
    if missing:
        raise InputError("missing-field", f"{label} is missing required fields")


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise InputError("unsafe-id", f"{label} is not a safe identifier")
    return value


def _slug(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SLUG_RE.fullmatch(value):
        raise InputError("unsafe-slug", f"{label} is not a lowercase safe slug")
    return value


def parse_utc_timestamp(value: Any, *, label: str = "timestamp") -> datetime:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise InputError("invalid-timestamp", f"{label} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputError("invalid-timestamp", f"{label} is not a real timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise InputError("invalid-timestamp", f"{label} must be UTC")
    return parsed


def _timestamp(value: Any, *, label: str = "observed_at") -> str:
    parse_utc_timestamp(value, label=label)
    return value


def _is_reserved_example_host(host: str) -> bool:
    return host in {"example.com", "example.net", "example.org"} or host.endswith((".example", ".example.com", ".test", ".invalid"))


def _site_url_v1(value: Any) -> str:
    """Keep the version 1 reserved-fixture URL contract unchanged."""
    if not isinstance(value, str) or not re.fullmatch(r"https://[a-z0-9.-]+(?:/[^\s]*)?", value):
        raise InputError("invalid-site", "site must be an HTTPS example-safe URL")
    host = value.split("/", 3)[2].split(":", 1)[0].lower()
    if not _is_reserved_example_host(host):
        raise InputError("unsafe-site", "public fixtures must use reserved example domains")
    return value


def canonical_public_origin(value: Any) -> str:
    """Validate and canonicalize an ASCII, public HTTPS origin for schema v2."""
    if not isinstance(value, str) or not value or len(value) > MAX_TEXT or not value.isascii():
        raise InputError("invalid-site", "site must be an ASCII HTTPS origin")
    if value != value.lower() or not value.startswith("https://"):
        raise InputError("invalid-site", "site must be a lowercase HTTPS origin")
    authority = value[len("https://") :]
    if authority.endswith("/"):
        authority = authority[:-1]
    if not authority or any(marker in authority for marker in ("@", ":", "/", "?", "#")):
        raise InputError("invalid-site", "site must not include credentials or a port")
    host = authority
    if host.endswith("."):
        raise InputError("invalid-site", "site host is not a canonical DNS hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise InputError("invalid-site", "site host must not be an IP literal")
    if host == "localhost" or host.endswith(".localhost") or PRIVATE_IDENTIFIER_RE.search(host):
        raise InputError("unsafe-site", "site host is not public-safe")
    if len(host) > 253:
        raise InputError("invalid-site", "site host is outside the public limit")
    labels = host.split(".")
    if any(not label or len(label) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise InputError("invalid-site", "site host is not a valid DNS hostname")
    return f"https://{host}"


def _digest_without_field(document: dict[str, Any], field: str) -> str:
    clone = dict(document)
    clone.pop(field, None)
    return hashlib.sha256(canonical_json(clone)).hexdigest()


def connector_evidence_identity(
    *,
    source_kind: str,
    provider: str,
    scope_ref: str,
    site_id: str,
    site_url: str,
    observation_window: dict[str, Any] | None,
    comparison_window: dict[str, Any] | None,
    observed_at: str,
    grain: str,
) -> dict[str, Any]:
    """Build the canonical, nonsecret Connector Envelope v1 identity tuple."""
    return {
        "source": source_kind,
        "provider": provider,
        "scope_ref": scope_ref,
        "site_id": site_id,
        "site_url": site_url,
        "observation_window": observation_window,
        "comparison_window": comparison_window,
        "collected_at": observed_at,
        "grain": grain,
    }


def connector_evidence_id_from_identity(identity: dict[str, Any]) -> str:
    """Return the fixed lowercase Base32 evidence ID for a canonical identity."""
    digest = hashlib.sha256(canonical_json(identity)).digest()
    prefix = base64.b32encode(digest).decode("ascii").rstrip("=").lower()[:EVIDENCE_ID_DIGEST_CHARS]
    return f"ev-{prefix}"


def _validate_digest(document: dict[str, Any], *, required: bool) -> None:
    if "input_digest" not in document:
        if required:
            raise InputError("missing-field", "root is missing required fields")
        return
    digest = document["input_digest"]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise InputError("digest", "input_digest must be lowercase SHA-256")
    if digest != _digest_without_field(document, "input_digest"):
        raise InputError("digest", "input_digest does not match the canonical document")


def _validate_window(value: Any, *, label: str) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise InputError("window", f"{label} must be an interval object")
    _require_keys(value, {"start", "end"}, {"start", "end"}, label)
    start = _timestamp(value["start"], label=f"{label}.start")
    end = _timestamp(value["end"], label=f"{label}.end")
    if parse_utc_timestamp(start, label=f"{label}.start") >= parse_utc_timestamp(end, label=f"{label}.end"):
        raise InputError("window", f"{label} must have start before end")
    return start, end


def _validate_measure_map(value: Any) -> None:
    if not isinstance(value, dict) or not value or len(value) > MAX_ITEMS:
        raise InputError("measures", "measures must be a non-empty bounded object")
    for name, measure in value.items():
        _slug(name, "measure")
        if not isinstance(measure, dict):
            raise InputError("measure", "each measure must be an object")
        _require_keys(measure, {"value", "unit"}, {"value", "unit"}, "measure")
        number = measure["value"]
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise InputError("measure", "measure value must be a finite JSON number")
        if isinstance(number, int):
            if number.bit_length() > MAX_NUMBER_TEXT * 4 or len(str(number)) > MAX_NUMBER_TEXT:
                raise InputError("measure", "measure value exceeds the public numeric limit")
        elif not math.isfinite(number):
            raise InputError("measure", "measure value must be a finite JSON number")
        _slug(measure["unit"], "measure unit")


def _validate_lineage(value: Any) -> None:
    if not isinstance(value, list) or not value or len(value) > MAX_ITEMS:
        raise InputError("lineage", "lineage must be a non-empty bounded array")
    provider_reference = False
    for item in value:
        if not isinstance(item, dict):
            raise InputError("lineage", "each lineage item must be an object")
        _require_keys(item, {"stage", "reference", "method"}, {"stage", "reference"}, "lineage")
        _slug(item["stage"], "lineage stage")
        reference = _id(item["reference"], "lineage reference")
        if reference == "provider_response_sha256":
            provider_reference = True
        if "method" in item:
            _slug(item["method"], "lineage method")
    if not provider_reference:
        raise InputError("lineage", "lineage must reference provider_response_sha256")


def _validate_v1_evidence(item: dict[str, Any], evidence_ids: set[str]) -> None:
    _require_keys(item, ALLOWED_EVIDENCE_V1, {"evidence_id", "source_kind", "observed_at", "completeness", "freshness", "uncertainty"}, "evidence")
    evidence_id = _id(item["evidence_id"], "evidence_id")
    if evidence_id in evidence_ids:
        raise InputError("duplicate-evidence", "evidence identifiers must be unique within a site")
    evidence_ids.add(evidence_id)
    if not isinstance(item["source_kind"], str) or not DOMAIN_RE.fullmatch(item["source_kind"].replace("_", "-")):
        raise InputError("source-kind", "source_kind must be a safe slug")
    _timestamp(item["observed_at"])
    if item["completeness"] not in COMPLETENESS or item["freshness"] not in FRESHNESS or item["uncertainty"] not in UNCERTAINTY:
        raise InputError("evidence-state", "evidence state is outside the public enum")
    if "summary" in item and (not isinstance(item["summary"], str) or not item["summary"].strip()):
        raise InputError("summary", "summary must be non-empty text")
    if "facts" in item and not isinstance(item["facts"], dict):
        raise InputError("facts", "facts must be an object")


def _validate_v2_evidence(item: dict[str, Any], evidence_ids: set[str], *, site_id: str, site_url: str) -> None:
    required = {"evidence_id", "source_kind", "observed_at", "completeness", "freshness", "uncertainty", "facts", "lineage", "provider_response_sha256"}
    _require_keys(item, ALLOWED_EVIDENCE_V2, required, "evidence")
    evidence_id = item["evidence_id"]
    if not isinstance(evidence_id, str) or not EVIDENCE_ID_RE.fullmatch(evidence_id):
        raise InputError("unsafe-id", "evidence_id is not a connector-safe identifier")
    if evidence_id in evidence_ids:
        raise InputError("duplicate-evidence", "evidence identifiers must be unique within a site")
    evidence_ids.add(evidence_id)
    _slug(item["source_kind"], "source_kind")
    observed_at = parse_utc_timestamp(item["observed_at"], label="observed_at")
    if item["completeness"] not in COMPLETENESS_V2 or item["freshness"] not in FRESHNESS_V2 or item["uncertainty"] not in UNCERTAINTY_V2:
        raise InputError("evidence-state", "evidence state is outside the public enum")
    digest = item["provider_response_sha256"]
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise InputError("digest", "provider_response_sha256 must be lowercase SHA-256")
    facts = item["facts"]
    if not isinstance(facts, dict):
        raise InputError("facts", "facts must be an object")
    _require_keys(facts, ALLOWED_FACTS_V2, {"provider", "scope_ref", "grain", "measures"}, "facts")
    _slug(facts["provider"], "provider")
    _id(facts["scope_ref"], "scope_ref")
    _slug(facts["grain"], "grain")
    _validate_measure_map(facts["measures"])
    observation: tuple[str, str] | None = None
    if "observation_window" in facts:
        observation = _validate_window(facts["observation_window"], label="observation_window")
        if parse_utc_timestamp(observation[1], label="observation_window.end") > observed_at:
            raise InputError("window", "observation window must end by observed_at")
    if "comparison_window" in facts:
        comparison = _validate_window(facts["comparison_window"], label="comparison_window")
        if parse_utc_timestamp(comparison[1], label="comparison_window.end") > observed_at:
            raise InputError("window", "comparison window must end by observed_at")
        if observation is not None and parse_utc_timestamp(comparison[1], label="comparison_window.end") > parse_utc_timestamp(observation[0], label="observation_window.start"):
            raise InputError("window", "comparison window must end before observation window")
    if "limitations" in facts and (not isinstance(facts["limitations"], str) or not facts["limitations"].strip() or len(facts["limitations"]) > MAX_TEXT):
        raise InputError("limitations", "limitations must be non-empty bounded text")
    _validate_lineage(item["lineage"])
    expected_evidence_id = connector_evidence_id_from_identity(
        connector_evidence_identity(
            source_kind=item["source_kind"],
            provider=facts["provider"],
            scope_ref=facts["scope_ref"],
            site_id=site_id,
            site_url=site_url,
            observation_window=facts.get("observation_window"),
            comparison_window=facts.get("comparison_window"),
            observed_at=item["observed_at"],
            grain=facts["grain"],
        )
    )
    if evidence_id != expected_evidence_id:
        raise InputError("evidence-identity", "evidence_id does not match the canonical connector identity")


def _validate_opportunities(site: dict[str, Any], evidence_ids: set[str]) -> None:
    opportunities = site["opportunities"]
    if not isinstance(opportunities, list) or len(opportunities) > MAX_ITEMS:
        raise InputError("opportunities", "opportunities must be a bounded array")
    opportunity_ids: set[str] = set()
    for item in opportunities:
        if not isinstance(item, dict):
            raise InputError("opportunity", "opportunity item must be an object")
        _require_keys(item, ALLOWED_OPPORTUNITY, {"opportunity_id", "domain", "title", "priority", "evidence_ids", "approval_gate"}, "opportunity")
        opportunity_id = _id(item["opportunity_id"], "opportunity_id")
        if opportunity_id in opportunity_ids:
            raise InputError("duplicate-opportunity", "opportunity identifiers must be unique within a site")
        opportunity_ids.add(opportunity_id)
        if not isinstance(item["domain"], str) or not DOMAIN_RE.fullmatch(item["domain"]):
            raise InputError("domain", "domain must be a safe slug")
        if not isinstance(item["title"], str) or not item["title"].strip():
            raise InputError("title", "opportunity title must be non-empty text")
        if not isinstance(item["priority"], int) or isinstance(item["priority"], bool) or not 0 <= item["priority"] <= 1000:
            raise InputError("priority", "priority must be an integer from 0 to 1000")
        refs = item["evidence_ids"]
        if not isinstance(refs, list) or not refs or len(refs) > MAX_ITEMS:
            raise InputError("lineage", "evidence_ids must be a non-empty bounded array")
        if len(set(refs)) != len(refs) or any(ref not in evidence_ids for ref in refs):
            raise InputError("lineage", "opportunity evidence lineage must reference unique site evidence")
        if not isinstance(item["approval_gate"], str) or not item["approval_gate"].strip() or len(item["approval_gate"]) > MAX_TEXT:
            raise InputError("approval-gate", "approval_gate must be non-empty bounded text")


def _document_digest_paths(document: dict[str, Any], version: str) -> set[tuple[Any, ...]]:
    paths: set[tuple[Any, ...]] = set()
    if "input_digest" in document:
        paths.add(("input_digest",))
    if version == SCHEMA_V2:
        for site_index, site in enumerate(document["sites"]):
            for evidence_index, evidence in enumerate(site["evidence"]):
                if "provider_response_sha256" in evidence:
                    paths.add(("sites", site_index, "evidence", evidence_index, "provider_response_sha256"))
    return paths


def validate_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise InputError("invalid-root", "input root must be an object")
    _require_keys(document, ALLOWED_TOP, {"schema_version", "sites"}, "root")
    version = document["schema_version"]
    if version not in {SCHEMA_VERSION, SCHEMA_V2}:
        raise InputError("schema-version", "unsupported schema version")
    if "run_id" in document:
        _id(document["run_id"], "run_id")
    _validate_digest(document, required=version == SCHEMA_V2)
    sites = document["sites"]
    if not isinstance(sites, list) or not sites or len(sites) > MAX_ITEMS:
        raise InputError("sites", "sites must be a non-empty bounded array")
    seen_sites: set[str] = set()
    for site in sites:
        if not isinstance(site, dict):
            raise InputError("site", "each site must be an object")
        _require_keys(site, ALLOWED_SITE, {"site_id", "site", "evidence", "opportunities"}, "site")
        site_id = _slug(site["site_id"], "site_id") if version == SCHEMA_V2 else _id(site["site_id"], "site_id")
        if site_id in seen_sites:
            raise InputError("duplicate-site", "site identifiers must be unique")
        seen_sites.add(site_id)
        if version == SCHEMA_V2:
            canonical = canonical_public_origin(site["site"])
            if site["site"] != canonical:
                raise InputError("invalid-site", "schema version 2 sites must be canonical origins")
        else:
            _site_url_v1(site["site"])
        evidence = site["evidence"]
        if not isinstance(evidence, list) or len(evidence) > MAX_ITEMS:
            raise InputError("evidence", "evidence must be a bounded array")
        evidence_ids: set[str] = set()
        for item in evidence:
            if not isinstance(item, dict):
                raise InputError("evidence", "evidence item must be an object")
            if version == SCHEMA_V2:
                _validate_v2_evidence(item, evidence_ids, site_id=site_id, site_url=canonical)
            else:
                _validate_v1_evidence(item, evidence_ids)
        _validate_opportunities(site, evidence_ids)
    _walk_limits(document)
    _walk_safety(document, allowed_digest_paths=_document_digest_paths(document, version))
    return document


def safe_path(path_value: str | os.PathLike[str], *, output: bool = False) -> Path:
    """Resolve a path while rejecting lexical traversal and symlink ancestors."""
    raw = os.fspath(path_value)
    if not raw or "\x00" in raw:
        raise PathSafetyError("path", "path is invalid")
    parts = Path(raw).parts
    if ".." in parts:
        raise PathSafetyError("path-traversal", "path traversal is not allowed")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = Path(os.path.abspath(path))
    if output and path == Path(path.anchor):
        raise PathSafetyError("output-root", "filesystem root is not a safe output directory")
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        if current.exists() and current.is_symlink() and current not in {Path("/tmp"), Path("/var")}:
            raise PathSafetyError("symlink-path", "symlink paths are not allowed")
    if output and path.exists() and not path.is_dir():
        raise PathSafetyError("output", "output path must be a directory")
    return path


def load_document(path_value: str | os.PathLike[str]) -> tuple[dict[str, Any], bytes, str]:
    path = safe_path(path_value)
    if not path.exists() or not path.is_file():
        raise InputError("input-path", "input file does not exist")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise InputError("input-read", "input file could not be read") from exc
    if len(raw) > MAX_BYTES:
        raise InputError("input-too-large", "input exceeds the 1 MB public boundary")
    document = _json_loads(raw)
    validate_document(document)
    return document, raw, hashlib.sha256(raw).hexdigest()


def parse_document_bytes(raw: bytes) -> dict[str, Any]:
    """Parse and validate exactly the bytes that a caller intends to execute."""
    if not isinstance(raw, bytes):
        raise InputError("input-bytes", "execution input must be immutable bytes")
    if len(raw) > MAX_BYTES:
        raise InputError("input-too-large", "input exceeds the 1 MB public boundary")
    document = _json_loads(raw)
    return validate_document(document)


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise InputError("non-finite-number", "canonical JSON cannot encode non-finite numbers") from exc
