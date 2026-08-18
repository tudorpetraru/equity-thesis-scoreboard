#!/usr/bin/env python3
"""Verify revealed call commitments using only the Python standard library."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def commitment_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return the originally sealed record.

    A later void is append-only lifecycle metadata. The original commitment
    therefore binds the record with ``voided`` set to null.
    """
    result = dict(record)
    result["voided"] = None
    return result


def canonical_json(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def commitment(record: dict[str, Any], salt: str) -> str:
    material = canonical_json(commitment_record(record)) + salt
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def verify(path: Path, call_id: str | None = None) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    selected = [row for row in payload["calls"] if call_id is None or row["call_id"] == call_id]
    if call_id and not selected:
        print(f"No call found for id {call_id}")
        return 2
    failures = 0
    revealed = 0
    for row in selected:
        if row["state"] != "revealed":
            print(f"SEALED   {row['call_id']} (not yet independently verifiable)")
            continue
        revealed += 1
        actual = commitment(row["record"], row["salt"])
        matches = actual == row["commitment"]
        print(f"{'MATCH' if matches else 'MISMATCH'}  {row['call_id']}")
        failures += int(not matches)
    print("\nCanonical JSON: UTF-8, keys sorted, separators ',' and ':', no ASCII escaping.")
    print("Commitment: SHA-256(canonical_json(record_at_seal) + 128-bit hex salt).")
    print("A later void is lifecycle metadata; verification restores voided=null.")
    print(f"Verified {revealed} revealed call(s); {failures} mismatch(es).")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="data/calls.json", type=Path)
    parser.add_argument("--call-id")
    args = parser.parse_args()
    return verify(args.path, args.call_id)


if __name__ == "__main__":
    raise SystemExit(main())
