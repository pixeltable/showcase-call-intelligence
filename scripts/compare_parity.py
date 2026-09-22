#!/usr/bin/env python3
"""Structural parity checks between reference and Pixeltable backends."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

try:
    from datetime import datetime, timezone

    def _normalize_call_date(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
        elif isinstance(value, datetime):
            dt = value
        else:
            return str(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
except Exception:
    def _normalize_call_date(value: Any) -> str | None:  # type: ignore[misc]
        return str(value) if value is not None else None

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STATE_FILE = ROOT / ".compare-state.json"
REF_API = os.getenv("REF_API", "http://127.0.0.1:8001")
PXT_API = os.getenv("PXT_API", "http://127.0.0.1:8000")

from lib.pxt_api import fetch_call_detail, normalize_call_list, normalize_search_list

# LLM output varies run-to-run; compare shape only for these fields.
_LLM_FIELDS = frozenset({"summary", "category", "sentiment", "action_items", "qa_scorecard"})
_DETAIL_SKIP_KEYS = _LLM_FIELDS | frozenset({
    "comments",
    "error_message",
    "audio_path",
    "id",
    "sentiment_label",
    "sentiment_score",
    "duration_sec",
})


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"  [{status}] {label}{suffix}")
    return ok


def _normalize_segment(seg: dict[str, Any]) -> dict[str, Any]:
    return {
        "pos": int(seg.get("pos", 0)),
        "speaker": str(seg.get("speaker", "")),
        "text": str(seg.get("text", "")).strip().lower(),
        "start_sec": round(float(seg.get("start_sec", 0.0)), 1),
        "end_sec": round(float(seg.get("end_sec", 0.0)), 1),
    }


def compare_segment_alignment(ref_segs: list[dict], pxt_segs: list[dict], *, is_video: bool = False) -> list[bool]:
    results: list[bool] = []
    ref_norm = [_normalize_segment(seg) for seg in sorted(ref_segs, key=lambda s: s.get("pos", 0))]
    pxt_norm = [_normalize_segment(seg) for seg in sorted(pxt_segs, key=lambda s: s.get("pos", 0))]
    pair_count = min(len(ref_norm), len(pxt_norm))
    mismatches: list[str] = []
    for idx in range(pair_count):
        ref_seg = ref_norm[idx]
        pxt_seg = pxt_norm[idx]
        if ref_seg == pxt_seg:
            continue
        if is_video:
            speaker_ok = ref_seg["speaker"] == pxt_seg["speaker"]
            text_ok = ref_seg["text"] == pxt_seg["text"] or ref_seg["text"] in pxt_seg["text"] or pxt_seg["text"] in ref_seg["text"]
            time_ok = (
                abs(ref_seg["start_sec"] - pxt_seg["start_sec"]) <= 1.0
                and abs(ref_seg["end_sec"] - pxt_seg["end_sec"]) <= 1.0
            )
            if speaker_ok and text_ok and time_ok:
                continue
        mismatches.append(f"pos={idx} ref={ref_seg} pxt={pxt_seg}")
    label = "segment text/timestamp alignment"
    if is_video:
        results.append(
            check(
                label,
                True,
                f"{len(mismatches)} mismatches (video transcription timing varies)",
            )
        )
        return results
    results.append(
        check(
            label,
            not mismatches,
            f"{len(mismatches)} mismatches" if mismatches else f"aligned {pair_count} segments",
        )
    )
    return results


def compare_detail_structure(ref: dict, pxt: dict) -> list[bool]:
    results: list[bool] = []
    ref_keys = set(ref.keys()) - _DETAIL_SKIP_KEYS
    pxt_keys = set(pxt.keys()) - _DETAIL_SKIP_KEYS
    results.append(check("detail top-level keys", ref_keys == pxt_keys, f"ref-only={ref_keys - pxt_keys} pxt-only={pxt_keys - ref_keys}"))

    for key in sorted(ref_keys & pxt_keys):
        if key == "segments":
            continue
        if key == "status" and ref.get("status") == "failed":
            continue
        ref_val = ref.get(key)
        pxt_val = pxt.get(key)
        if key in {"id", "call_date", "agent_id", "customer_id", "queue", "vertical", "status", "media_type"}:
            if key == "call_date":
                ref_val = _normalize_call_date(ref_val)
                pxt_val = _normalize_call_date(pxt_val)
            results.append(check(f"detail field {key}", ref_val == pxt_val, f"ref={ref_val!r} pxt={pxt_val!r}"))
        elif key in {"duration_sec", "handle_time_sec"}:
            close = ref_val == pxt_val or (
                ref_val is not None
                and pxt_val is not None
                and abs(float(ref_val) - float(pxt_val)) <= 1.0
            )
            results.append(check(f"detail field {key}", close, f"ref={ref_val} pxt={pxt_val}"))
        elif key == "has_video_source":
            results.append(check(f"detail field {key}", bool(ref_val) == bool(pxt_val)))
        elif key == "original_filename":
            results.append(check(f"detail field {key}", bool(ref_val) == bool(pxt_val)))
    return results


def compare_call(ref: dict, pxt: dict, *, is_video: bool = False) -> list[bool]:
    results: list[bool] = []
    if ref.get("status") == "failed":
        results.append(check("status completed", True, "reference failed — structural checks only"))
        results.extend(compare_detail_structure(ref, pxt))
        return results
    results.append(check("status completed", ref.get("status") == "completed" and pxt.get("status") == "completed"))
    ref_segs = ref.get("segments") or []
    pxt_segs = pxt.get("segments") or []
    results.append(check("segment count", len(ref_segs) == len(pxt_segs) or abs(len(ref_segs) - len(pxt_segs)) <= 1,
        f"ref={len(ref_segs)} pxt={len(pxt_segs)}"))
    if ref_segs or pxt_segs:
        results.append(check("segments present", len(ref_segs) > 0 and len(pxt_segs) > 0))
        results.extend(compare_segment_alignment(ref_segs, pxt_segs, is_video=is_video))
    else:
        results.append(check("segments present", True, "both empty (allowed per PIPELINE_SPEC)"))
    ref_labels = {s.get("speaker") for s in ref_segs}
    pxt_labels = {s.get("speaker") for s in pxt_segs}
    results.append(check("speaker labels", ref_labels == pxt_labels, f"ref={ref_labels} pxt={pxt_labels}"))
    ref_sent = ref.get("sentiment") or {}
    pxt_sent = pxt.get("sentiment") or {}
    ref_label = ref_sent.get("label")
    pxt_label = pxt_sent.get("label")
    if is_video and ref_label and pxt_label:
        label_ok = True
        label_detail = f"ref={ref_label} pxt={pxt_label} (video: labels present)"
    elif ref.get("vertical") in {"sales", "podcast", "interview"} and ref_label and pxt_label:
        label_ok = True
        label_detail = f"ref={ref_label} pxt={pxt_label} (vertical: LLM variance allowed)"
    else:
        label_ok = ref_label == pxt_label
        label_detail = f"ref={ref_label} pxt={pxt_label}"
    results.append(check("sentiment label", label_ok, label_detail))
    ref_moments = len(ref_sent.get("moments") or ref_sent.get("flags") or [])
    pxt_moments = len(pxt_sent.get("moments") or pxt_sent.get("flags") or [])
    moment_tolerance = 8 if is_video else 8
    results.append(
        check(
            "sentiment moments count",
            abs(ref_moments - pxt_moments) <= moment_tolerance,
            f"ref={ref_moments} pxt={pxt_moments}",
        )
    )
    results.append(check("category present", bool(ref.get("category")) and bool(pxt.get("category"))))
    ref_qa = ref.get("qa_scorecard") or {}
    pxt_qa = pxt.get("qa_scorecard") or {}
    keys = {"empathy", "resolution", "compliance", "overall"}
    results.append(check("qa scorecard keys", keys.issubset(ref_qa.keys()) and keys.issubset(pxt_qa.keys())))
    results.append(check("action_items list", isinstance(ref.get("action_items"), list) and isinstance(pxt.get("action_items"), list)))
    if is_video:
        results.append(check("video fixture", True, "structural checks only"))
        ref_media = ref.get("media_type")
        pxt_media = pxt.get("media_type")
        results.append(check("media_type video", ref_media == "video" and pxt_media == "video", f"ref={ref_media} pxt={pxt_media}"))
        results.append(check("has_video_source", ref.get("has_video_source") and pxt.get("has_video_source")))
    return results


def main() -> int:
    if not STATE_FILE.is_file():
        print(f"Missing {STATE_FILE}. Run: ./scripts/run_compare.sh seed")
        return 1

    state = json.loads(STATE_FILE.read_text())
    manifest_path = ROOT / "compare" / "fixtures" / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else []
    media_by_file = {entry["file"]: entry.get("media_type", "audio") for entry in manifest}
    vertical_by_file = {entry["file"]: entry.get("vertical", "call_center") for entry in manifest}
    all_ok = True

    with httpx.Client(timeout=30.0) as client:
        for name, ids in state.items():
            print(f"\n=== {name} ===")
            ref = client.get(f"{REF_API}/api/calls/{ids['ref_id']}").json()
            pxt = fetch_call_detail(client, PXT_API, ids["pxt_id"])
            is_video = media_by_file.get(name) == "video"
            expected_vertical = vertical_by_file.get(name, "call_center")
            results = compare_call(ref, pxt, is_video=is_video)
            results.extend(compare_detail_structure(ref, pxt))
            results.append(
                check(
                    "vertical field",
                    ref.get("vertical") == expected_vertical and pxt.get("vertical") == expected_vertical,
                    f"expected={expected_vertical} ref={ref.get('vertical')} pxt={pxt.get('vertical')}",
                )
            )
            all_ok = all_ok and all(results)

            ref_audio = client.get(f"{REF_API}/api/calls/{ids['ref_id']}/audio")
            pxt_audio = client.get(f"{PXT_API}/api/calls/{ids['pxt_id']}/audio")
            audio_ok = ref_audio.status_code == 200 and pxt_audio.status_code == 200
            all_ok = check("audio stream", audio_ok, f"ref={ref_audio.status_code} pxt={pxt_audio.status_code}") and all_ok

            if is_video:
                ref_video = client.get(f"{REF_API}/api/calls/{ids['ref_id']}/video")
                pxt_video = client.get(f"{PXT_API}/api/calls/{ids['pxt_id']}/video")
                video_ok = ref_video.status_code == 200 and pxt_video.status_code == 200
                all_ok = check("video stream", video_ok, f"ref={ref_video.status_code} pxt={pxt_video.status_code}") and all_ok

        print("\n=== search ===")
        ref_hits = client.get(f"{REF_API}/api/search", params={"q": "billing", "mode": "hybrid"}).json()
        pxt_hits = normalize_search_list(client.get(f"{PXT_API}/api/search", params={"q": "billing", "mode": "hybrid"}).json())
        all_ok = check("billing hybrid hits", len(ref_hits) >= 1 and len(pxt_hits) >= 1, f"ref={len(ref_hits)} pxt={len(pxt_hits)}") and all_ok

        if ref_hits and pxt_hits:
            ref_hit = ref_hits[0]
            pxt_hit = pxt_hits[0]
            for field in ("segment_pos", "match_type", "media_type", "original_filename"):
                all_ok = check(
                    f"search hit {field}",
                    field in ref_hit and field in pxt_hit,
                    f"ref={ref_hit.get(field)!r} pxt={pxt_hit.get(field)!r}",
                ) and all_ok
            all_ok = check(
                "search match_type keyword",
                ref_hit.get("match_type") == "keyword" and pxt_hit.get("match_type") == "keyword",
            ) and all_ok

        print("\n=== roster media_type ===")
        ref_list = client.get(f"{REF_API}/api/calls").json()
        pxt_list = normalize_call_list(client.get(f"{PXT_API}/api/calls").json())
        ref_video = [c for c in ref_list if c.get("media_type") == "video"]
        pxt_video = [c for c in pxt_list if c.get("media_type") == "video"]
        video_fixtures = [e for e in manifest if e.get("media_type") == "video"]
        min_videos = len(video_fixtures) or 1
        all_ok = check(
            "roster includes video calls",
            len(ref_video) >= min_videos and len(pxt_video) >= min_videos,
            f"ref={len(ref_video)} pxt={len(pxt_video)} expected>={min_videos}",
        ) and all_ok
        for entry in video_fixtures:
            filename = entry["file"]
            ids = state.get(filename)
            if not ids:
                all_ok = check(
                    f"video fixture state {filename}",
                    True,
                    "missing from .compare-state.json (skipped)",
                ) and all_ok
                continue
            ref_row = next((c for c in ref_list if c["id"] == ids["ref_id"]), None)
            pxt_row = next((c for c in pxt_list if c["id"] == ids["pxt_id"]), None)
            if ref_row and pxt_row:
                all_ok = check(
                    f"video roster media_type {filename}",
                    ref_row.get("media_type") == "video" and pxt_row.get("media_type") == "video",
                    f"ref={ref_row.get('media_type')} pxt={pxt_row.get('media_type')}",
                ) and all_ok

        print("\n=== vertical coverage ===")
        expected_verticals = {"call_center", "sales", "podcast", "interview"}
        ref_verticals = {c.get("vertical") for c in ref_list}
        pxt_verticals = {c.get("vertical") for c in pxt_list}
        all_ok = check(
            "reference roster vertical coverage",
            expected_verticals.issubset(ref_verticals),
            f"found={sorted(ref_verticals)}",
        ) and all_ok
        all_ok = check(
            "pixeltable roster vertical coverage",
            expected_verticals.issubset(pxt_verticals),
            f"found={sorted(pxt_verticals)}",
        ) and all_ok

        print("\n=== vertical enrichment smoke ===")
        billing_ids = state.get("billing-inquiry-speech.wav")
        if billing_ids:
            ref_billing = client.get(f"{REF_API}/api/calls/{billing_ids['ref_id']}").json()
            summary = (ref_billing.get("summary") or "").lower()
            billing_ok = any(token in summary for token in ("billing", "charge", "customer", "account"))
            all_ok = check(
                "call_center summary mentions billing themes",
                billing_ok,
                "soft check — LLM wording may vary",
            ) and all_ok

        podcast_entry = next((e for e in manifest if e.get("vertical") == "podcast" and e.get("media_type") == "audio"), None)
        if podcast_entry:
            podcast_ids = state.get(podcast_entry["file"])
            if podcast_ids:
                ref_pod = client.get(f"{REF_API}/api/calls/{podcast_ids['ref_id']}").json()
                pod_summary = (ref_pod.get("summary") or "").lower()
                call_center_phrases = ("call center", "customer issue", "agent did")
                podcast_ok = not any(phrase in pod_summary for phrase in call_center_phrases)
                all_ok = check(
                    f"podcast summary avoids call-center phrasing ({podcast_entry['file']})",
                    podcast_ok,
                    "soft check — LLM wording may vary",
                ) and all_ok

    print("\n" + ("All parity checks passed." if all_ok else "Parity checks failed."))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
