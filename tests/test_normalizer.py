from __future__ import annotations

import base64
import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from evidence_loop.errors import InputError, PathSafetyError
from evidence_loop.normalizer import (
    EVIDENCE_ID_DIGEST_CHARS,
    load_envelope,
    normalize_envelopes,
    parse_envelope_bytes,
    validate_envelope,
)
from evidence_loop.schema import MAX_BASE64_DECODE_DEPTH, MAX_BYTES, MAX_ITEMS, canonical_json, validate_document


ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 12, 31, tzinfo=timezone.utc)


def fixture(name: str = "connector-envelope.json") -> dict:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


class NormalizerTests(unittest.TestCase):
    def test_parse_and_normalize_one_or_many_envelopes_deterministically(self):
        first = parse_envelope_bytes((ROOT / "examples" / "connector-envelope.json").read_bytes())
        second = parse_envelope_bytes((ROOT / "examples" / "connector-envelope-second.json").read_bytes())
        single = normalize_envelopes([first], AS_OF)
        self.assertEqual(single["schema_version"], "2")
        self.assertEqual(single["sites"][0]["site"], "https://alpha.example")
        self.assertEqual(single["sites"][0]["opportunities"], [])
        self.assertRegex(single["sites"][0]["evidence"][0]["evidence_id"], rf"^ev-[a-z2-7]{{{EVIDENCE_ID_DIGEST_CHARS}}}$")
        many = normalize_envelopes([first, second], AS_OF)
        self.assertEqual(many, normalize_envelopes([second, first], AS_OF))
        self.assertEqual(len(many["sites"][0]["evidence"]), 2)
        self.assertEqual(validate_document(many), many)
        expected = hashlib.sha256(canonical_json({key: value for key, value in many.items() if key != "input_digest"})).hexdigest()
        self.assertEqual(many["input_digest"], expected)

    def test_envelope_structure_measure_lineage_and_state_rejections(self):
        with self.assertRaises(InputError) as duplicate:
            parse_envelope_bytes(b'{"schema_version":"1","schema_version":"1"}')
        self.assertEqual(duplicate.exception.code, "duplicate-key")
        variants: list[tuple[str, object]] = [
            ("unknown", {"unknown": True}),
            ("source", "Not-Lowercase"),
            ("measures", {"observations": {"value": True, "unit": "count"}}),
            ("measures", {"observations": {"value": float("inf"), "unit": "count"}}),
            ("lineage", []),
            ("lineage", [{"stage": "provider-response", "reference": "other", "method": "sha256"}]),
            ("completeness", "missing"),
        ]
        for key, value in variants:
            envelope = fixture()
            if key == "unknown":
                envelope.update(value)  # type: ignore[arg-type]
            else:
                envelope[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(InputError):
                validate_envelope(envelope)
        envelope = fixture()
        envelope["measures"] = {f"metric-{index}": {"value": index, "unit": "count"} for index in range(MAX_ITEMS + 1)}
        with self.assertRaises(InputError):
            validate_envelope(envelope)

    def test_time_windows_site_conflicts_duplicates_and_collision_fail_closed(self):
        invalids = []
        reversed_window = fixture()
        reversed_window["observation_window"] = {"start": "2026-07-19T10:00:00Z", "end": "2026-07-19T09:00:00Z"}
        invalids.append(reversed_window)
        future_window = fixture()
        future_window["observation_window"]["end"] = "2026-07-19T10:00:01Z"
        invalids.append(future_window)
        comparison_without_observation = fixture()
        comparison_without_observation.pop("observation_window")
        comparison_without_observation["comparison_window"]["end"] = "2026-07-19T10:00:01Z"
        invalids.append(comparison_without_observation)
        overlap = fixture()
        overlap["comparison_window"]["end"] = overlap["observation_window"]["start"]
        overlap["comparison_window"]["end"] = "2026-07-18T00:00:01Z"
        invalids.append(overlap)
        for envelope in invalids:
            with self.assertRaises(InputError):
                validate_envelope(envelope)
        future_collection = fixture()
        future_collection["collected_at"] = "2027-01-01T00:00:00Z"
        with self.assertRaises(InputError):
            normalize_envelopes([future_collection], AS_OF)
        first = fixture()
        second = fixture("connector-envelope-second.json")
        conflicting = copy.deepcopy(second)
        conflicting["site_url"] = "https://beta.example"
        with self.assertRaises(InputError):
            normalize_envelopes([first, conflicting], AS_OF)
        with self.assertRaises(InputError):
            normalize_envelopes([first, copy.deepcopy(first)], AS_OF)
        forced = "ev-" + "a" * EVIDENCE_ID_DIGEST_CHARS
        with mock.patch("evidence_loop.normalizer._evidence_id", return_value=forced), self.assertRaises(InputError):
            normalize_envelopes([first, second], AS_OF)

    def test_url_policy_v1_and_v2_and_private_markers(self):
        bad_urls = [
            "https://user@alpha.example",
            "https://alpha.example:443",
            "https://alpha.example/path",
            "https://alpha.example?query=yes",
            "https://alpha.example#fragment",
            "https://127.0.0.1",
            "https://localhost",
            "https://sub.localhost",
            "https://bad_.example",
            "https://property-id.example",
        ]
        for site_url in bad_urls:
            envelope = fixture()
            envelope["site_url"] = site_url
            with self.subTest(site_url=site_url), self.assertRaises(InputError):
                validate_envelope(envelope)
        real = fixture()
        real["site_url"] = "https://public.example.org"
        document = normalize_envelopes([real], AS_OF)
        self.assertEqual(document["sites"][0]["site"], "https://public.example.org")
        v1 = {
            "schema_version": "1",
            "sites": [{"site_id": "real", "site": "https://public.example.org", "evidence": [], "opportunities": []}],
        }
        with self.assertRaises(InputError):
            validate_document(v1)
        for unsafe in ("project-id", "provider-id"):
            envelope = fixture()
            envelope["scope_ref"] = unsafe
            with self.assertRaises(InputError):
                validate_envelope(envelope)

    def test_provider_style_scope_aliases_and_common_token_shapes_are_rejected(self):
        for prefix in (
            "provider_",
            "property_",
            "properties_",
            "project_",
            "team_",
            "account_",
            "tenant_",
            "workspace_",
            "organization_",
            "org_",
            "user_",
            "uid_",
            "session_",
            "prj_",
            "dpl_",
            "acct_",
            "usr_",
        ):
            envelope = fixture()
            envelope["scope_ref"] = prefix + "a" * 24
            with self.subTest(prefix=prefix), self.assertRaises(InputError):
                validate_envelope(envelope)
            wrapped = fixture()
            wrapped["limitations"] = base64.urlsafe_b64encode((prefix + "a" * 24).encode("utf-8")).decode("ascii").rstrip("=")
            with self.subTest(wrapped_prefix=prefix), self.assertRaises(InputError):
                validate_envelope(wrapped)
        for private_identifier in ("account_customer7", "a50e8400-e29b-41d4-a716-446655440000"):
            envelope = fixture()
            envelope["scope_ref"] = private_identifier
            with self.subTest(private_identifier=private_identifier), self.assertRaises(InputError):
                validate_envelope(envelope)
            wrapped = fixture()
            wrapped["limitations"] = base64.urlsafe_b64encode(private_identifier.encode("utf-8")).decode("ascii").rstrip("=")
            with self.subTest(wrapped_identifier=private_identifier), self.assertRaises(InputError):
                validate_envelope(wrapped)
        for unsafe_alias in ("team_alpha9", "properties-123456789"):
            envelope = fixture()
            envelope["scope_ref"] = unsafe_alias
            with self.subTest(unsafe_alias=unsafe_alias), self.assertRaises(InputError):
                validate_envelope(envelope)
            wrapped = fixture()
            wrapped["limitations"] = base64.urlsafe_b64encode(unsafe_alias.encode("utf-8")).decode("ascii").rstrip("=")
            with self.subTest(wrapped_alias=unsafe_alias), self.assertRaises(InputError):
                validate_envelope(wrapped)
        for private_identifier in (
            "session_abcdef123456",
            "team_abcdefghijklmnop",
            "project_abcdefghijklmnop",
            "uid_abcdef123456",
        ):
            direct = fixture()
            direct["scope_ref"] = private_identifier
            with self.subTest(direct_identifier=private_identifier), self.assertRaises(InputError):
                validate_envelope(direct)
            wrapped = fixture()
            wrapped["limitations"] = base64.urlsafe_b64encode(private_identifier.encode("utf-8")).decode("ascii").rstrip("=")
            with self.subTest(wrapped_identifier=private_identifier), self.assertRaises(InputError):
                validate_envelope(wrapped)
        for safe_alias in ("public-alpha", "team-plan", "project-plan", "properties-summary"):
            envelope = fixture()
            envelope["scope_ref"] = safe_alias
            with self.subTest(safe_alias=safe_alias):
                validate_envelope(envelope)
        for unsafe in (
            "Bearer " + "x" * 24,
            "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12,
            "xoxb-" + "a" * 24,
        ):
            envelope = fixture()
            envelope["limitations"] = unsafe
            with self.assertRaises(InputError):
                validate_envelope(envelope)

    def test_digest_separation_and_nested_base64_safety(self):
        envelope = fixture()
        accepted = validate_envelope(envelope)
        self.assertEqual(accepted["provider_response_sha256"], envelope["provider_response_sha256"])
        self.assertEqual(accepted["lineage"][0]["reference"], "provider_response_sha256")
        duplicate_digest = fixture()
        duplicate_digest["limitations"] = duplicate_digest["provider_response_sha256"]
        with self.assertRaises(InputError):
            validate_envelope(duplicate_digest)
        wrapped = fixture()
        wrapped["limitations"] = base64.urlsafe_b64encode(("api" + "_key=wrapped-value").encode("utf-8")).decode("ascii").rstrip("=")
        with self.assertRaises(InputError):
            validate_envelope(wrapped)
        nested = fixture()
        nested["limitations"] = base64.b64encode(("/" + "Users/unsafe").encode("utf-8")).decode("ascii")
        with self.assertRaises(InputError):
            validate_envelope(nested)
        secret = ("api" + "_key=hidden-value").encode("utf-8")
        layered = secret
        for _ in range(3):
            layered = base64.b64encode(layered)
        depth_three = fixture()
        depth_three["limitations"] = layered.decode("ascii")
        with self.assertRaises(InputError):
            validate_envelope(depth_three)
        layered = secret
        for _ in range(MAX_BASE64_DECODE_DEPTH + 1):
            layered = base64.urlsafe_b64encode(layered).rstrip(b"=")
        at_ceiling = fixture()
        at_ceiling["limitations"] = layered.decode("ascii")
        with self.assertRaises(InputError):
            validate_envelope(at_ceiling)
        safe = fixture()
        safe["limitations"] = base64.urlsafe_b64encode(b"ordinary safe text").decode("ascii").rstrip("=")
        validate_envelope(safe)

    def test_direct_huge_integer_and_aggregate_boundaries_fail_closed(self):
        huge_integer = fixture()
        huge_integer["measures"]["observations"]["value"] = 10**1000
        with self.assertRaises(InputError):
            validate_envelope(huge_integer)
        base = fixture()
        measure = {f"metric{index:03d}": {"value": index, "unit": "unit" + "x" * 59} for index in range(MAX_ITEMS)}
        envelopes = []
        for index in range(1, MAX_ITEMS + 1):
            envelope = copy.deepcopy(base)
            envelope["source"] = f"source-{index:03d}"
            envelope["measures"] = measure
            envelope["limitations"] = "x" * 512
            envelopes.append(envelope)
            if len(canonical_json(envelopes)) > MAX_BYTES:
                break
        self.assertGreater(len(canonical_json(envelopes)), MAX_BYTES)
        with self.assertRaises(InputError):
            normalize_envelopes(envelopes, AS_OF)

    def test_path_safety_and_as_of_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "envelope.json"
            source.write_bytes((ROOT / "examples" / "connector-envelope.json").read_bytes())
            link = root / "link.json"
            link.symlink_to(source)
            with self.assertRaises(PathSafetyError):
                load_envelope(link)
            with self.assertRaises(PathSafetyError):
                load_envelope(root / ".." / "envelope.json")
        with self.assertRaises(InputError):
            normalize_envelopes([fixture()], datetime(2026, 12, 31))
