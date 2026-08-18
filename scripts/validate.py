#!/usr/bin/env python3
"""Validate the public call contract and append-only history."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT_KEYS = {"format_version", "methodology_version", "embargo_days", "calls"}
SEALED_KEYS = {"call_id", "state", "sealed_at", "commitment", "methodology_version"}
REVEALED_KEYS = SEALED_KEYS | {"salt", "record"}
RECORD_KEYS = {
    "ticker", "company", "rating", "conviction", "generated_at", "research_as_of",
    "price_in_thesis", "target_price", "stop_price", "thesis_statement", "pdf_sha256",
    "pdf_size_bytes", "schema_version", "provenance", "voided",
}
RATINGS = {"STRONG_BUY", "BUY", "HOLD", "SELL", "STRONG_SELL"}
CONVICTIONS = {"HIGH", "MEDIUM-HIGH", "MEDIUM", "LOW"}
ISO_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
HEX_RE = re.compile(r"^[0-9a-f]+$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_record(record: Any, call_id: str) -> None:
    require(isinstance(record, dict), f"{call_id}: record must be an object")
    require(set(record) == RECORD_KEYS, f"{call_id}: record fields violate the contract")
    require(isinstance(record["ticker"], str) and record["ticker"] == record["ticker"].upper(), f"{call_id}: ticker")
    require(isinstance(record["company"], str) and bool(record["company"]), f"{call_id}: company")
    require(record["rating"] in RATINGS, f"{call_id}: rating")
    require(record["conviction"] in CONVICTIONS, f"{call_id}: conviction")
    require(isinstance(record["generated_at"], str) and ISO_RE.match(record["generated_at"]) is not None, f"{call_id}: generated_at")
    require(record["research_as_of"] is None or isinstance(record["research_as_of"], str), f"{call_id}: research_as_of")
    for name in ("price_in_thesis", "stop_price"):
        require(record[name] is None or isinstance(record[name], (int, float)), f"{call_id}: {name}")
    require(isinstance(record["target_price"], (int, float)), f"{call_id}: target_price")
    require(isinstance(record["thesis_statement"], str) and bool(record["thesis_statement"]), f"{call_id}: thesis_statement")
    require(isinstance(record["pdf_sha256"], str) and len(record["pdf_sha256"]) == 64 and HEX_RE.match(record["pdf_sha256"]) is not None, f"{call_id}: pdf_sha256")
    require(isinstance(record["pdf_size_bytes"], int) and record["pdf_size_bytes"] > 0, f"{call_id}: pdf_size_bytes")
    require(isinstance(record["schema_version"], str), f"{call_id}: schema_version")
    require(record["provenance"] in {"live", "backfilled"}, f"{call_id}: provenance")
    if record["voided"] is not None:
        require(set(record["voided"]) == {"at", "reason"}, f"{call_id}: voided fields")
        require(ISO_RE.match(record["voided"]["at"]) is not None and bool(record["voided"]["reason"]), f"{call_id}: voided")


def validate(payload: Any) -> None:
    require(isinstance(payload, dict) and set(payload) == ROOT_KEYS, "root fields violate the contract")
    require(payload["format_version"] == 1 and payload["methodology_version"] == 1, "unsupported version")
    require(isinstance(payload["embargo_days"], int) and payload["embargo_days"] >= 0, "embargo_days")
    require(isinstance(payload["calls"], list), "calls must be an array")
    ids: set[str] = set()
    order: list[tuple[str, str]] = []
    for row in payload["calls"]:
        require(isinstance(row, dict), "call entry must be an object")
        call_id = row.get("call_id")
        require(isinstance(call_id, str) and len(call_id) == 16 and HEX_RE.match(call_id) is not None, "call_id")
        require(call_id not in ids, f"duplicate call_id {call_id}")
        ids.add(call_id)
        require(row.get("state") in {"sealed", "revealed"}, f"{call_id}: state")
        expected = SEALED_KEYS if row["state"] == "sealed" else REVEALED_KEYS
        require(set(row) == expected, f"{call_id}: entry fields violate the contract")
        require(ISO_RE.match(row["sealed_at"]) is not None, f"{call_id}: sealed_at")
        require(row["methodology_version"] == 1, f"{call_id}: methodology_version")
        require(len(row["commitment"]) == 64 and HEX_RE.match(row["commitment"]) is not None, f"{call_id}: commitment")
        if row["state"] == "revealed":
            require(len(row["salt"]) == 32 and HEX_RE.match(row["salt"]) is not None, f"{call_id}: salt")
            validate_record(row["record"], call_id)
        order.append((row["sealed_at"], call_id))
    require(order == sorted(order), "calls must be ordered by sealed_at then call_id")


def validate_append_only(previous: Any, current: Any) -> None:
    validate(previous)
    validate(current)
    before = previous["calls"]
    after = current["calls"]
    require(len(after) >= len(before), "calls may not be deleted")
    for index, old in enumerate(before):
        new = after[index]
        require(old["call_id"] == new["call_id"], "calls may not be reordered or replaced")
        if old["state"] == "sealed":
            require(new["state"] in {"sealed", "revealed"}, f"{old['call_id']}: invalid lifecycle")
            for key in SEALED_KEYS - {"state"}:
                require(old[key] == new[key], f"{old['call_id']}: sealed proof changed")
        else:
            require(new["state"] == "revealed", f"{old['call_id']}: revealed call cannot be resealed")
            old_copy = json.loads(json.dumps(old))
            new_copy = json.loads(json.dumps(new))
            old_void = old_copy["record"].pop("voided")
            new_void = new_copy["record"].pop("voided")
            require(old_copy == new_copy, f"{old['call_id']}: revealed record changed")
            if old_void is None:
                require(new_void is None or isinstance(new_void, dict), f"{old['call_id']}: invalid void")
            else:
                require(old_void == new_void, f"{old['call_id']}: published void changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current", type=Path)
    parser.add_argument("--previous", type=Path)
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))
    if args.previous:
        previous = json.loads(args.previous.read_text(encoding="utf-8"))
        validate_append_only(previous, current)
    else:
        validate(current)
    print("calls.json is valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
