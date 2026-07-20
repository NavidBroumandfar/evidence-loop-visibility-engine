from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from evidence_loop.errors import InputError, PathSafetyError
from evidence_loop.schema import MAX_BYTES, canonical_json, load_document, parse_document_bytes, validate_document


ROOT = Path(__file__).resolve().parents[1]


def fixture(name: str) -> dict:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


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

    def test_input_digest_exact_semantics(self):
        document = fixture("clean-no-op.json")
        document["input_digest"] = __import__("hashlib").sha256(canonical_json(document)).hexdigest()
        validate_document(document)
        document["input_digest"] = "0" * 64
        with self.assertRaises(InputError):
            validate_document(document)

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

    def test_conservative_numeric_hooks_reject_huge_tokens(self):
        with self.assertRaises(InputError) as integer_error:
            parse_document_bytes((b'{"schema_version":"1","sites":[],"n":' + b"9" * 5000 + b"}"))
        self.assertIn(integer_error.exception.code, {"number-too-large", "unknown-field"})
        nested = b"[" * 2000 + b"0" + b"]" * 2000
        with self.assertRaises(InputError):
            parse_document_bytes(nested)
