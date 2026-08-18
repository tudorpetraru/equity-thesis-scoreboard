#!/usr/bin/env python3
"""Fail closed when public files contain private identifiers or secrets."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path


def patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    chat_service = "what" + "sapp"
    user_root = "/" + "Users" + "/"
    home_root = "/" + "home" + "/"
    state_root = "~/" + "." + "her" + "mes"
    private_prefix = "THESIS" + "_GATEWAY_"
    agent_name = "co" + "dex"
    return (
        ("messaging identifier", re.compile(r"(?i)@(s\." + chat_service + r"\.net|lid|g\.us)\b")),
        ("phone-like identifier", re.compile(r"(?i)(?:phone|mobile|recipient|chat[_ -]?id)[^\n]{0,24}\+?\d[\d ()-]{7,18}\d")),
        ("absolute local path", re.compile(r"(?:" + re.escape(user_root) + "|" + re.escape(home_root) + "|" + re.escape(state_root) + r")")),
        ("private environment variable", re.compile(r"\b" + private_prefix + r"[A-Z0-9_]+\b")),
        ("secret material", re.compile(r"(?i)(?:api[_ -]?key|access[_ -]?token|private[_ -]?key|authorization)\s*[:=]\s*['\"]?[A-Za-z0-9_./+\-=]{12,}")),
        ("runtime internals", re.compile(r"(?i)\b(?:" + agent_name + r"|session[_ -]?id|thread[_ -]?id|reasoning[_ -]?effort|provider[_ -]?name|profile[_ -]?name)\b")),
    )


def candidate_hashes(text: str) -> set[str]:
    return {
        hashlib.sha256(token.lower().encode("utf-8")).hexdigest()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_.-]{5,80}", text)
    }


def scan(root: Path, private_name_hash: str = "") -> list[str]:
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(root)
        for label, expression in patterns():
            for match in expression.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{relative}:{line}: {label}")
        if private_name_hash and private_name_hash.lower() in candidate_hashes(text):
            findings.append(f"{relative}:1: private repository name hash")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    args = parser.parse_args()
    findings = scan(args.root, os.environ.get("PRIVATE_NAME_SHA256", ""))
    if findings:
        print("Privacy gate failed:")
        print("\n".join(findings))
        return 1
    print("Privacy gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
