from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from evidence_loop.errors import InputError, PathSafetyError
from evidence_loop.normalizer import normalize_envelopes
from evidence_loop.schema import MAX_BYTES, canonical_json, load_document, parse_document_bytes, validate_document


ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 12, 31, tzinfo=timezone.utc)


def fixture(name: str) -> dict:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


def normalized_fixture() -> dict:
    return normalize_envelopes([fixture("connector-envelope.json")], AS_OF)


def refresh_input_digest(document: dict) -> None:
    document["input_digest"] = hashlib.sha256(
        canonical_json({key: value for key, value in document.items() if key != "input_digest"})
    ).hexdigest()


class SchemaTests(unittest.TestCase):
    def test_valid_fixture_and_all_domains(self):
        self.assertEqual(len(validate_document(fixture("normal.json"))["sites"]), 2)
        self.assertEqual(len(validate_document(fixture("all-domains.json"))["sites"][0]["opportunities"]), 8)

    def test_duplicate_keys_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duplicate.json"
            path.write_text('{"schema_version":"1","schema_version":"1","sites":[]}', encoding="utf-8")
            with self.assertRaises(InputError) as ctx:
                load_document(path)
            self.assertEqual(ctx.exception.code, "duplicate-key")

    def test_depth_and_text_limits(self):
        document = fixture("normal.json")
        document["sites"][0]["evidence"][0]["summary"] = "x" * 513
        with self.assertRaises(InputError):
            validate_document(document)
        document = fixture("normal.json")
        nested = value = {}
        for _ in range(10):
            value["x"] = {}
            value = value["x"]
        document["sites"][0]["evidence"][0]["facts"] = nested
        with self.assertRaises(InputError):
            validate_document(document)

    def test_one_mb_inclusive_and_one_byte_over(self):
        raw_base = canonical_json(fixture("clean-no-op.json"))
        exact = raw_base + b" " * (MAX_BYTES - len(raw_base))
        over = exact + b" "
        with tempfile.TemporaryDirectory() as temp:
            exact_path = Path(temp) / "exact.json"
            exact_path.write_bytes(exact)
            document, raw, _ = load_document(exact_path)
            self.assertEqual(len(raw), MAX_BYTES)
            self.assertEqual(document["run_id"], "demo-clean")
            over_path = Path(temp) / "over.json"
            over_path.write_bytes(over)
            with self.assertRaises(InputError) as ctx:
                load_document(over_path)
            self.assertEqual(ctx.exception.code, "input-too-large")

    def test_exact_boundary_is_enforced_inside_execution_parser(self):
        raw_base = canonical_json(fixture("clean-no-op.json"))
        exact = raw_base + b" " * (MAX_BYTES - len(raw_base))
        parsed = parse_document_bytes(exact)
        self.assertEqual(parsed["run_id"], "demo-clean")
        with self.assertRaises(InputError) as ctx:
            parse_document_bytes(exact + b" ")
        self.assertEqual(ctx.exception.code, "input-too-large")

    def test_non_finite_json_numbers_rejected(self):
        document = fixture("normal.json")
        document["sites"][0]["evidence"][0]["facts"] = {"number": float("nan")}
        with self.assertRaises(InputError):
            canonical_json(document)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "nan.json"
            path.write_text('{"schema_version":"1","sites":[],"facts":NaN}', encoding="utf-8")
            with self.assertRaises(InputError) as ctx:
                load_document(path)
            self.assertEqual(ctx.exception.code, "non-finite-number")

    def test_secret_nested_wrapped_and_safe_base64(self):
        document = fixture("normal.json")
        document["sites"][0]["evidence"][0]["facts"] = {"nested": {"note": "api" + "_key=badvalue"}}
        with self.assertRaises(InputError):
            validate_document(document)
        document = fixture("normal.json")
        wrapped = base64.b64encode(b"sec" + b"ret: hidden-value").decode("ascii")
        document["sites"][0]["evidence"][0]["facts"] = {"nested": wrapped}
        with self.assertRaises(InputError):
            validate_document(document)
        document = fixture("normal.json")
        document["sites"][0]["evidence"][0]["facts"] = {"note": base64.b64encode(b"hello world").decode("ascii")}
        validate_document(document)
        document["sites"][0]["evidence"][0]["facts"] = {"digest": "a" * 64}
        with self.assertRaises(InputError):
            validate_document(document)
        document = fixture("normal.json")
        document["sites"][0]["evidence"][0]["facts"] = {"token": "ordinary-looking-value"}
        with self.assertRaises(InputError):
            validate_document(document)

    def test_private_posix_and_windows_paths_reject_direct_and_wrapped_forms(self):
        posix = lambda root, suffix: "/" + root + suffix
        backslash = "\\"
        drive = "C:"
        private_paths = (
            "see(" + posix("Users", "/alice/private-file") + ")",
            posix("home", "/alice/private-file"),
            posix("private", "/tmp/private-file"),
            posix("var", "/folders/alice/private-file"),
            posix("tmp", "/private-file"),
            posix("usr", "/local/private-file"),
            posix("opt", "/private-file"),
            posix("var", "/log/private-file"),
            posix("Library", "/Application Support/private-file"),
            posix("System", "/private-file"),
            posix("Volumes", "/private/private-file"),
            "file" + "://server/" + "Users/alice/private-file",
            posix("etc", "/private-file"),
            posix("root", "/private-file"),
            drive + backslash + "Users" + backslash + "alice" + backslash + "private-file",
            drive + backslash * 2 + "Users" + backslash * 2 + "alice" + backslash * 2 + "private-file",
            drive + "/" + "Users/alice/private-file",
            backslash * 2 + "server" + backslash + "Users" + backslash + "alice" + backslash + "private-file",
            "/" * 2 + "server/" + "Users/alice/private-file",
            backslash * 2 + "server" + backslash + "share" + backslash + "Users" + backslash + "alice" + backslash + "private-file",
        )
        for value in private_paths:
            direct = fixture("normal.json")
            direct["sites"][0]["evidence"][0]["facts"] = {"note": value}
            with self.subTest(form="direct", value=value), self.assertRaises(InputError):
                validate_document(direct)
            wrapped = fixture("normal.json")
            wrapped["sites"][0]["evidence"][0]["facts"] = {"note": base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")}
            with self.subTest(form="wrapped", value=value), self.assertRaises(InputError):
                validate_document(wrapped)
        for safe_text in ("ordinary public text", "https://public.example.org/" + "Users/guide"):
            document = fixture("normal.json")
            document["sites"][0]["evidence"][0]["facts"] = {"note": safe_text}
            with self.subTest(safe_text=safe_text):
                validate_document(document)

    def test_uuid_identifiers_reject_direct_and_wrapped_forms(self):
        identifier = "a50e8400-e29b-41d4-a716-446655440000"
        direct = fixture("normal.json")
        direct["sites"][0]["evidence"][0]["facts"] = {"note": identifier}
        with self.assertRaises(InputError):
            validate_document(direct)
        wrapped = fixture("normal.json")
        wrapped["sites"][0]["evidence"][0]["facts"] = {"note": base64.urlsafe_b64encode(identifier.encode("utf-8")).decode("ascii").rstrip("=")}
        with self.assertRaises(InputError):
            validate_document(wrapped)

    def test_input_digest_exact_semantics(self):
        document = fixture("clean-no-op.json")
        document["input_digest"] = __import__("hashlib").sha256(canonical_json(document)).hexdigest()
        validate_document(document)
        document["input_digest"] = "0" * 64
        with self.assertRaises(InputError):
            validate_document(document)

    def test_digest_field_names_are_allowed_only_at_exact_paths(self):
        document = fixture("normal.json")
        document["sites"][0]["evidence"][0]["facts"] = {"provider_response_sha256": "ordinary-safe-value"}
        with self.assertRaises(InputError):
            validate_document(document)
        document = fixture("normal.json")
        document["sites"][0]["evidence"][0]["facts"] = {"nested": {"input_digest": "ordinary-safe-value"}}
        with self.assertRaises(InputError):
            validate_document(document)

        top_level = fixture("clean-no-op.json")
        top_level["input_digest"] = __import__("hashlib").sha256(canonical_json(top_level)).hexdigest()
        validate_document(top_level)
        self.assertEqual(validate_document(normalized_fixture())["schema_version"], "2")

    def test_symlink_input_and_ancestor_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.json"
            source.write_text(json.dumps(fixture("clean-no-op.json")), encoding="utf-8")
            direct = root / "direct.json"
            direct.symlink_to(source)
            with self.assertRaises(PathSafetyError):
                load_document(direct)
            parent = root / "real-parent"
            parent.mkdir()
            (parent / "file.json").write_text(source.read_text(), encoding="utf-8")
            link_parent = root / "link-parent"
            link_parent.symlink_to(parent, target_is_directory=True)
            with self.assertRaises(PathSafetyError):
                load_document(link_parent / "file.json")

    def test_digest_field_is_the_only_allowed_digest_marker(self):
        document = fixture("clean-no-op.json")
        document["sites"][0]["evidence"][0]["facts"] = {"nested": {"hash": "b" * 64}}
        with self.assertRaises(InputError):
            validate_document(document)
        for field in ("input_digest", "provider_response_sha256"):
            document = fixture("clean-no-op.json")
            document["sites"][0]["evidence"][0]["facts"] = {field: "b" * 64}
            with self.subTest(field=field), self.assertRaises(InputError):
                validate_document(document)

    def test_conservative_numeric_hooks_reject_huge_tokens(self):
        with self.assertRaises(InputError) as integer_error:
            parse_document_bytes((b'{"schema_version":"1","sites":[],"n":' + b"9" * 5000 + b"}"))
        self.assertIn(integer_error.exception.code, {"number-too-large", "unknown-field"})
        nested = b"[" * 2000 + b"0" + b"]" * 2000
        with self.assertRaises(InputError):
            parse_document_bytes(nested)

    def test_schema_v2_rechecks_time_order_without_observation_window(self):
        document = normalized_fixture()
        facts = document["sites"][0]["evidence"][0]["facts"]
        facts.pop("observation_window")
        facts["comparison_window"]["end"] = "2026-07-19T10:00:01Z"
        refresh_input_digest(document)
        with self.assertRaises(InputError) as ctx:
            validate_document(document)
        self.assertEqual(ctx.exception.code, "window")

    def test_schema_v2_rechecks_canonical_evidence_identity_after_digest_refresh(self):
        def evidence(document: dict) -> dict:
            return document["sites"][0]["evidence"][0]

        mutations = {
            "site-url": lambda document: document["sites"][0].update(site="https://beta.example"),
            "site-id": lambda document: document["sites"][0].update(site_id="site-beta"),
            "provider": lambda document: evidence(document)["facts"].update(provider="other-provider"),
            "scope": lambda document: evidence(document)["facts"].update(scope_ref="public-beta"),
            "observation-window": lambda document: evidence(document)["facts"]["observation_window"].update(start="2026-07-18T00:00:01Z"),
            "comparison-window": lambda document: evidence(document)["facts"]["comparison_window"].update(start="2026-07-16T00:00:01Z"),
            "observed-at": lambda document: evidence(document).update(observed_at="2026-07-19T10:00:01Z"),
            "grain": lambda document: evidence(document)["facts"].update(grain="page-level"),
            "source": lambda document: evidence(document).update(source_kind="other-source"),
        }
        baseline = normalized_fixture()
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                document = copy.deepcopy(baseline)
                mutate(document)
                refresh_input_digest(document)
                with self.assertRaises(InputError) as ctx:
                    validate_document(document)
                self.assertEqual(ctx.exception.code, "evidence-identity")
