from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from evidence_loop.capabilities import CAPABILITIES, route
from evidence_loop.engine import execute, persist, receipt_digest
from evidence_loop.schema import canonical_json


ROOT = Path(__file__).resolve().parents[1]


def fixture(name: str) -> dict:
    return json.loads((ROOT / "examples" / name).read_text(encoding="utf-8"))


class EngineTests(unittest.TestCase):
    def test_all_eight_capabilities_are_allowlisted(self):
        self.assertEqual(len(CAPABILITIES), 8)
        for name in CAPABILITIES:
            self.assertIsNotNone(route(name))
            self.assertEqual(route(name).version, "1.0")

    def test_deterministic_selection_and_freshness_change(self):
        doc = fixture("normal.json")
        first = execute(canonical_json(doc))
        self.assertEqual(first["sites"][0]["selected_opportunity_id"], "alpha-technical-1")
        doc["sites"][0]["evidence"][0]["freshness"] = "stale"
        doc["sites"][0]["opportunities"][1]["priority"] = 2
        # Both opportunities share stale evidence, so the changed observation
        # correctly produces a no-op rather than retaining a stale choice.
        second = execute(canonical_json(doc))
        self.assertIsNone(second["sites"][0]["selected_opportunity_id"])

    def test_lineage_and_approval_boundary(self):
        doc = fixture("normal.json")
        receipt = execute(canonical_json(doc))
        proposal = receipt["sites"][0]["proposal"]
        self.assertEqual(proposal["evidence_ids"], ["alpha-crawl-1"])
        self.assertEqual(receipt["sites"][0]["evidence"][0]["source_kind"], "search-console")
        self.assertEqual(receipt["sites"][0]["evidence"][0]["freshness"], "fresh")
        self.assertTrue(proposal["approval_required"])
        self.assertFalse(proposal["mutation_allowed"])
        self.assertEqual(receipt["receipt_sha256"], receipt_digest(receipt))

    def test_site_failure_is_contained(self):
        doc = fixture("contained-site-failure.json")
        receipt = execute(canonical_json(doc))
        statuses = {item["site_id"]: item["status"] for item in receipt["sites"]}
        self.assertEqual(statuses, {"site-healthy": "approval-required", "site-contained": "blocked"})
        self.assertEqual(receipt["terminal_state"], "approval-required")

    def test_terminal_states(self):
        for name, expected in [("normal.json", "approval-required"), ("clean-no-op.json", "clean-no-op"), ("contained-site-failure.json", "approval-required")]:
            doc = fixture(name)
            receipt = execute(canonical_json(doc))
            self.assertEqual(receipt["terminal_state"], expected)
        doc = fixture("contained-site-failure.json")
        doc["sites"][0]["opportunities"][0]["domain"] = "also-unsupported"
        receipt = execute(canonical_json(doc))
        self.assertEqual(receipt["terminal_state"], "blocked")

    def test_atomic_last_success_preservation(self):
        doc = fixture("normal.json")
        receipt = execute(canonical_json(doc))
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            persist(receipt, output)
            previous = (output / "last-success.json").read_bytes()
            with mock.patch("evidence_loop.engine._atomic_write", side_effect=[None, OSError("simulated")]):
                with self.assertRaises(OSError):
                    persist(receipt, output)
            self.assertEqual((output / "last-success.json").read_bytes(), previous)

    def test_child_symlink_output_rejected(self):
        doc = fixture("clean-no-op.json")
        receipt = execute(canonical_json(doc))
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "child").mkdir()
            (output / "child" / "link").symlink_to(output / "child")
            with self.assertRaises(Exception):
                persist(receipt, output)

    def test_execute_hashes_exact_raw_bytes_and_rejects_injected_digest(self):
        raw = b'{"schema_version":"1","sites":[{"site_id":"s","site":"https://s.example","evidence":[],"opportunities":[]}]}'
        # Empty evidence/opportunity lanes are valid and produce a clean no-op.
        receipt = execute(raw)
        self.assertEqual(receipt["input_sha256"], __import__("hashlib").sha256(raw).hexdigest())
        with self.assertRaises(TypeError):
            execute(json.loads(raw), "injected")  # type: ignore[arg-type]

    def test_mixed_unknown_capability_blocks_entire_site_lane(self):
        doc = fixture("normal.json")
        site = doc["sites"][0]
        site["opportunities"].append({"opportunity_id": "alpha-unknown", "domain": "future-module", "title": "Unknown", "priority": 0, "evidence_ids": ["alpha-crawl-1"], "approval_gate": "human-review"})
        receipt = execute(canonical_json(doc))
        alpha = receipt["sites"][0]
        self.assertEqual(alpha["status"], "blocked")
        self.assertIsNone(alpha["proposal"])
        self.assertEqual(receipt["sites"][1]["status"], "approval-required")

    def test_stale_high_priority_falls_back_to_fresh_lower_priority(self):
        doc = fixture("normal.json")
        site = doc["sites"][0]
        site["evidence"].append({"evidence_id": "alpha-fresh-2", "source_kind": "manual-observation", "observed_at": "2026-01-15T11:00:00Z", "completeness": "complete", "freshness": "fresh", "uncertainty": "low"})
        site["evidence"][0]["freshness"] = "stale"
        site["opportunities"][0]["priority"] = 1
        site["opportunities"].append({"opportunity_id": "alpha-fresh-2", "domain": "technical-seo", "title": "Fresh fallback", "priority": 20, "evidence_ids": ["alpha-fresh-2"], "approval_gate": "human-review"})
        receipt = execute(canonical_json(doc))
        self.assertEqual(receipt["sites"][0]["selected_opportunity_id"], "alpha-fresh-2")

    def test_verifier_failure_blocks_without_proposal(self):
        doc = fixture("normal.json")
        with mock.patch("evidence_loop.engine._proposal", return_value={"site_id": "wrong", "approval_required": True, "mutation_allowed": False}):
            receipt = execute(canonical_json(doc))
        self.assertEqual(receipt["sites"][0]["status"], "blocked")
        self.assertEqual(receipt["sites"][0]["blocked_reason"], "proposal-verification-failed")
        self.assertIsNone(receipt["sites"][0]["proposal"])

    def test_receipt_terminal_blocked_has_no_last_success_update(self):
        doc = fixture("contained-site-failure.json")
        doc["sites"][0]["opportunities"][0]["domain"] = "unsupported-lane"
        receipt = execute(canonical_json(doc))
        self.assertEqual(receipt["terminal_state"], "blocked")
        with tempfile.TemporaryDirectory() as temp:
            path = persist(receipt, temp)
            self.assertTrue(path.exists())
            self.assertFalse((Path(temp) / "last-success.json").exists())

    def test_clean_noop_plus_blocked_is_globally_blocked(self):
        doc = fixture("clean-no-op.json")
        blocked_site = json.loads(json.dumps(doc["sites"]))[0]
        blocked_site["site_id"] = "site-blocked"
        blocked_site["site"] = "https://blocked.example"
        blocked_site["opportunities"][0]["opportunity_id"] = "blocked-opportunity"
        blocked_site["opportunities"][0]["domain"] = "unsupported-lane"
        doc["sites"].append(blocked_site)
        receipt = execute(canonical_json(doc))
        self.assertEqual([item["status"] for item in receipt["sites"]], ["clean-no-op", "blocked"])
        self.assertEqual(receipt["terminal_state"], "blocked")
        with tempfile.TemporaryDirectory() as temp:
            persist(receipt, temp)
            self.assertFalse((Path(temp) / "last-success.json").exists())
