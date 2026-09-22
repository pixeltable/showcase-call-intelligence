#!/usr/bin/env python3
"""Smoke test enriched search API on both backends."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.pxt_api import fetch_call_detail, normalize_search_list

REF_API = os.getenv("REF_API", "http://127.0.0.1:8001")
PXT_API = os.getenv("PXT_API", "http://127.0.0.1:8000")
REQUIRED_FIELDS = {
    "call_id",
    "segment_id",
    "segment_pos",
    "match_type",
    "media_type",
    "original_filename",
    "text",
}


def _search_hits(payload, base_url: str) -> list[dict]:
    if base_url.rstrip("/") == PXT_API.rstrip("/"):
        return normalize_search_list(payload)
    return payload if isinstance(payload, list) else []


def _call_status(client: httpx.Client, base_url: str, call_id: str) -> str | None:
    if base_url.rstrip("/") == PXT_API.rstrip("/"):
        try:
            return fetch_call_detail(client, base_url, call_id).get("status")
        except Exception:
            return None
    resp = client.get(f"{base_url}/api/calls/{call_id}")
    if resp.status_code != 200:
        return None
    return resp.json().get("status")


def check_query(client: httpx.Client, base_url: str, label: str, query: str) -> bool:
    ok = True
    resp = client.get(f"{base_url}/api/search", params={"q": query, "mode": "hybrid"})
    if resp.status_code != 200:
        print(f"[FAIL] {label} search HTTP {resp.status_code} for {query!r}")
        return False
    hits = _search_hits(resp.json(), base_url)
    if not hits:
        print(f"[FAIL] {label} search returned no hits for {query!r}")
        return False
    hit = hits[0]
    missing = REQUIRED_FIELDS - set(hit.keys())
    if missing:
        print(f"[FAIL] {label} search hit missing fields: {sorted(missing)}")
        ok = False
    else:
        print(
            f"[PASS] {label} search {query!r} "
            f"match_type={hit['match_type']} media_type={hit['media_type']} "
            f"segment_pos={hit['segment_pos']}"
        )

    for h in hits[:5]:
        status = _call_status(client, base_url, h["call_id"])
        if status != "completed":
            print(f"[FAIL] {label} search hit call {h['call_id'][:8]}… status={status!r} (expected completed)")
            ok = False
    if ok and hits:
        print(f"[PASS] {label} search hits for {query!r} are from completed calls")
    return ok


def check_semantic(client: httpx.Client, base_url: str, label: str) -> bool:
    """Semantic search needs HF embed model and populated segment embeddings."""
    resp = client.get(f"{base_url}/api/search", params={"q": "monthly subscription fees", "mode": "semantic", "limit": 5})
    if resp.status_code != 200:
        print(f"[FAIL] {label} semantic search HTTP {resp.status_code}")
        return False
    hits = _search_hits(resp.json(), base_url)
    if not hits:
        health = client.get(f"{base_url}/api/health")
        detail = ""
        if health.status_code == 200:
            embed = health.json().get("checks", {}).get("embed_model", {})
            if not embed.get("ok"):
                detail = f" ({embed.get('detail')})"
        print(
            f"[FAIL] {label} semantic search returned no hits{detail}. "
            "Ensure EMBED_MODEL is installed (first seed downloads from Hugging Face Hub)."
        )
        return False
    if hits[0].get("match_type") != "semantic":
        print(f"[FAIL] {label} semantic search hit has match_type={hits[0].get('match_type')!r}")
        return False
    print(f"[PASS] {label} semantic search returned {len(hits)} hit(s)")
    return True


def check_backend(client: httpx.Client, base_url: str, label: str) -> bool:
    ok = check_query(client, base_url, label, "billing")
    ok = check_query(client, base_url, label, "cancel") and ok
    ok = check_semantic(client, base_url, label) and ok

    empty = client.get(f"{base_url}/api/search", params={"q": "zzzznotfound999", "mode": "hybrid"})
    if empty.status_code != 200:
        print(f"[FAIL] {label} empty search HTTP {empty.status_code}")
        ok = False
    elif empty.json():
        print(f"[WARN] {label} unexpected hits for nonsense query")
    else:
        print(f"[PASS] {label} empty query returns []")
    return ok


def main() -> int:
    with httpx.Client(timeout=30.0) as client:
        ref_ok = check_backend(client, REF_API, "Reference")
        pxt_ok = check_backend(client, PXT_API, "Pixeltable")
    return 0 if ref_ok and pxt_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
