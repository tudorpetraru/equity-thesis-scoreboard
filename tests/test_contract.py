from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.sanitize import scan
from scripts.validate import validate, validate_append_only
from scripts.verify import commitment


def record() -> dict:
    return {
        "ticker": "TEST", "company": "Test Company", "rating": "HOLD", "conviction": "MEDIUM",
        "generated_at": "2026-01-01T12:00:00Z", "research_as_of": None, "price_in_thesis": 100.0,
        "target_price": 110.0, "stop_price": 90.0, "thesis_statement": "A falsifiable statement.",
        "pdf_sha256": "a" * 64, "pdf_size_bytes": 1000, "schema_version": "2",
        "provenance": "live", "voided": None,
    }


def payload(entry: dict) -> dict:
    return {"format_version": 1, "methodology_version": 1, "embargo_days": 30, "calls": [entry]}


class ContractTest(unittest.TestCase):
    def test_commitment_round_trip(self):
        salt = "b" * 32
        expected = commitment(record(), salt)
        self.assertEqual(expected, commitment(dict(reversed(list(record().items()))), salt))

    def test_schema_rejects_unknown_record_field(self):
        row = record()
        row["extra"] = True
        entry = {"call_id": "1" * 16, "state": "revealed", "sealed_at": "2026-01-01T12:00:00Z", "commitment": "a" * 64, "methodology_version": 1, "salt": "b" * 32, "record": row}
        with self.assertRaises(ValueError):
            validate(payload(entry))

    def test_schema_accepts_medium_high_conviction(self):
        row = record()
        row["conviction"] = "MEDIUM-HIGH"
        entry = {"call_id": "1" * 16, "state": "revealed", "sealed_at": "2026-01-01T12:00:00Z", "commitment": "a" * 64, "methodology_version": 1, "salt": "b" * 32, "record": row}
        validate(payload(entry))

    def test_append_only_allows_reveal_but_rejects_edit(self):
        sealed = {"call_id": "1" * 16, "state": "sealed", "sealed_at": "2026-01-01T12:00:00Z", "commitment": "a" * 64, "methodology_version": 1}
        revealed = dict(sealed, state="revealed", salt="b" * 32, record=record())
        validate_append_only(payload(sealed), payload(revealed))
        edited = json.loads(json.dumps(revealed))
        edited["record"]["target_price"] = 999
        with self.assertRaises(ValueError):
            validate_append_only(payload(revealed), payload(edited))

    def test_sanitizer_blocks_planted_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            planted = "recipient: " + chr(43) + "40 " + str(721_234_567)
            (root / "bad.txt").write_text(planted, encoding="utf-8")
            self.assertTrue(scan(root))


if __name__ == "__main__":
    unittest.main()
