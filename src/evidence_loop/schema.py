"""Strict, offline input handling and public safety checks.

The parser intentionally accepts a small schema. It rejects duplicate JSON
keys and unsafe strings before any planning or output path is touched.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
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
SCHEMA_VERSION = "1"

ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]{0,63}$")
DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
PRIVATE_PATH_RE = re.compile(
    r"(?:^|[\s:=])/(?:Users|home|private|var/folders|etc|root)(?:[/\s]|$)", re.I
)
ASSIGNMENT_RE = re.compile(
    r"(?i)(?:api[_ -]?key|access[_ -]?token|auth(?:entication)?[_ -]?token|secret|password|private[_ -]?key|bearer)\s*[:=]"
)
TOKEN_RE = re.compile(r"(?i)(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})")
HEX64_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
SECRET_KEY_RE = re.compile(r"(?i)^(?:api[_ -]?key|access[_ -]?token|auth(?:entication)?[_ -]?token|token|secret|password|private[_ -]?key)$")

ALLOWED_TOP = {"schema_version", "run_id", "input_digest", "sites"}
ALLOWED_SITE = {"site_id", "site", "evidence", "opportunities"}
ALLOWED_EVIDENCE = {
    "evidence_id",
    "source_kind",
    "observed_at",
    "completeness",
    "freshness",
    "uncertainty",
    "summary",
    "facts",
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

    def reject_constant(value: str) -> Any:
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


def _looks_like_base64(value: str) -> bool:
    return len(value) >= 16 and len(value) % 4 == 0 and bool(re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", value))


def _scan_text(value: str) -> None:
    if PRIVATE_PATH_RE.search(value) or ASSIGNMENT_RE.search(value) or TOKEN_RE.search(value):
        raise InputError("unsafe-string", "input contains a private path or credential marker")
    if HEX64_RE.search(value.lower()):
        raise InputError("unsafe-string", "input contains a token-like digest marker")
    if _looks_like_base64(value):
        try:
            decoded = base64.b64decode(value, validate=True).decode("utf-8", "ignore")
        except (binascii.Error, ValueError):
            decoded = ""
        if decoded and (
            PRIVATE_PATH_RE.search(decoded)
            or ASSIGNMENT_RE.search(decoded)
            or TOKEN_RE.search(decoded)
            or "BEGIN PRIVATE KEY" in decoded.upper()
            or "provider_id" in decoded.lower()
        ):
            raise InputError("unsafe-string", "input contains a wrapped credential marker")


def _walk_safety(value: Any, *, key: str | None = None) -> None:
    stack: list[tuple[Any, str | None]] = [(value, key)]
    while stack:
        current, current_key = stack.pop()
        if isinstance(current, dict):
            for child_key, child in current.items():
                _scan_text(child_key)
                if SECRET_KEY_RE.fullmatch(child_key) and child_key != "input_digest":
                    raise InputError("unsafe-string", "input contains a credential-like field")
                stack.append((child, child_key))
        elif isinstance(current, list):
            stack.extend((child, None) for child in current)
        elif isinstance(current, str) and current_key != "input_digest":
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


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise InputError("invalid-timestamp", "observed_at must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InputError("invalid-timestamp", "observed_at is not a real timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise InputError("invalid-timestamp", "observed_at must be UTC")
    return value


def _site_url(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"https://[a-z0-9.-]+(?:/[^\s]*)?", value):
        raise InputError("invalid-site", "site must be an HTTPS example-safe URL")
    host = value.split("/", 3)[2].split(":", 1)[0].lower()
    reserved_exact = {"example.com", "example.net", "example.org"}
    if not (host in reserved_exact or host.endswith(".example") or host.endswith(".example.com") or host.endswith(".test") or host.endswith(".invalid")):
        raise InputError("unsafe-site", "public fixtures must use reserved example domains")
    return value


def _digest_without_field(document: dict[str, Any], field: str) -> str:
    clone = dict(document)
    clone.pop(field, None)
    encoded = json.dumps(clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_document(document: Any) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise InputError("invalid-root", "input root must be an object")
    _require_keys(document, ALLOWED_TOP, {"schema_version", "sites"}, "root")
    if document["schema_version"] != SCHEMA_VERSION:
        raise InputError("schema-version", "unsupported schema version")
    if "run_id" in document:
        _id(document["run_id"], "run_id")
    if "input_digest" in document:
        digest = document["input_digest"]
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise InputError("digest", "input_digest must be lowercase SHA-256")
        if digest != _digest_without_field(document, "input_digest"):
            raise InputError("digest", "input_digest does not match the canonical document")
    sites = document["sites"]
    if not isinstance(sites, list) or not sites or len(sites) > MAX_ITEMS:
        raise InputError("sites", "sites must be a non-empty bounded array")
    seen_sites: set[str] = set()
    for site in sites:
        if not isinstance(site, dict):
            raise InputError("site", "each site must be an object")
        _require_keys(site, ALLOWED_SITE, {"site_id", "site", "evidence", "opportunities"}, "site")
        site_id = _id(site["site_id"], "site_id")
        if site_id in seen_sites:
            raise InputError("duplicate-site", "site identifiers must be unique")
        seen_sites.add(site_id)
        _site_url(site["site"])
        evidence = site["evidence"]
        opportunities = site["opportunities"]
        if not isinstance(evidence, list) or len(evidence) > MAX_ITEMS:
            raise InputError("evidence", "evidence must be a bounded array")
        if not isinstance(opportunities, list) or len(opportunities) > MAX_ITEMS:
            raise InputError("opportunities", "opportunities must be a bounded array")
        evidence_ids: set[str] = set()
        for item in evidence:
            if not isinstance(item, dict):
                raise InputError("evidence", "evidence item must be an object")
            _require_keys(item, ALLOWED_EVIDENCE, {"evidence_id", "source_kind", "observed_at", "completeness", "freshness", "uncertainty"}, "evidence")
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
    _walk_limits(document)
    _walk_safety(document)
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
    # Walk every existing component from the filesystem root. This catches a
    # symlink in a parent even when the leaf itself does not yet exist.
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        # macOS exposes the system temporary and variable directories as
        # stable aliases; they are not user-controlled traversal points. Any
        # symlink below them (or any other component) remains rejected.
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
