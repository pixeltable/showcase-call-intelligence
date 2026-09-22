"""Normalize Pixeltable native API responses to reference-shaped dicts for compare scripts."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MAPPING = json.loads((ROOT / "compare" / "pxt_api_mapping.json").read_text())
SEGMENT_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def segment_uuid(call_id: uuid.UUID | str, pos: int) -> uuid.UUID:
    return uuid.uuid5(SEGMENT_NAMESPACE, f"{call_id}:{pos}")


def _sentiment_fields(sentiment: Any) -> tuple[str | None, float | None, dict | None]:
    if not isinstance(sentiment, dict):
        return None, None, None
    label = sentiment.get("label")
    score = sentiment.get("score")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    return str(label) if label else None, score_f, sentiment


def _first_error(row: dict[str, Any]) -> str | None:
    for key in MAPPING["detail_error_fields"]:
        value = row.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return None


def normalize_call_summary(row: dict[str, Any]) -> dict[str, Any]:
    label, score, _ = _sentiment_fields(row.get("sentiment"))
    call_id = row.get("uuid") or row.get("id")
    return {
        "id": str(call_id),
        "call_date": row.get("call_date"),
        "agent_id": row.get("agent_id") or "",
        "customer_id": row.get("customer_id") or "",
        "queue": row.get("queue") or "",
        "vertical": row.get("vertical") or "call_center",
        "duration_sec": row.get("duration_sec"),
        "handle_time_sec": row.get("handle_time_sec"),
        "status": (
            "failed"
            if _first_error(row)
            else row.get("pipeline_status") or row.get("status") or "transcribing"
        ),
        "category": row.get("category"),
        "summary": row.get("summary"),
        "sentiment_label": label,
        "sentiment_score": score,
        "media_type": row.get("media_type") or "audio",
        "has_video_source": bool(row.get("has_video_source")),
    }


def normalize_call_detail(row: dict[str, Any], comments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    summary = normalize_call_summary(row)
    call_id = uuid.UUID(str(summary["id"]))
    _, _, sentiment = _sentiment_fields(row.get("sentiment"))
    segments_raw = row.get("segments") or []
    segments: list[dict[str, Any]] = []
    if isinstance(segments_raw, list):
        for idx, seg in enumerate(segments_raw):
            if not isinstance(seg, dict):
                continue
            segments.append(
                {
                    "id": str(segment_uuid(call_id, idx)),
                    "speaker": str(seg.get("speaker") or "UNKNOWN"),
                    "start_sec": float(seg.get("start_sec", 0.0)),
                    "end_sec": float(seg.get("end_sec", 0.0)),
                    "text": str(seg.get("text", "")),
                    "pos": idx,
                }
            )
    comment_rows = comments or []
    normalized_comments: list[dict[str, Any]] = []
    for comment in comment_rows:
        pos = comment.get("segment_pos")
        seg_id = None
        if pos is not None and int(pos) >= 0:
            seg_id = str(segment_uuid(call_id, int(pos)))
        normalized_comments.append(
            {
                "id": str(comment.get("uuid") or comment.get("id")),
                "call_id": str(call_id),
                "segment_id": seg_id,
                "start_sec": float(comment.get("start_sec", 0.0)),
                "author": str(comment.get("author", "")),
                "comment": str(comment.get("comment", "")),
                "created_at": comment.get("timestamp") or comment.get("created_at"),
            }
        )
    return {
        **summary,
        "audio_path": row.get("audio_url") or f"/api/calls/{call_id}/audio",
        "original_filename": row.get("original_filename") or "",
        "action_items": row.get("action_items"),
        "sentiment": sentiment,
        "qa_scorecard": row.get("qa_scorecard"),
        "error_message": _first_error(row),
        "segments": segments,
        "comments": normalized_comments,
    }


def normalize_search_hit(row: dict[str, Any]) -> dict[str, Any]:
    call_id = row.get("call_uuid") or row.get("call_id") or row.get("uuid")
    pos = int(row.get("segment_pos", row.get("pos", 0)))
    call_uuid_obj = uuid.UUID(str(call_id))
    media_type = row.get("media_type") or "audio"
    match_type = row.get("match_type") or "keyword"
    return {
        "call_id": str(call_uuid_obj),
        "segment_id": str(segment_uuid(call_uuid_obj, pos)),
        "agent_id": str(row.get("agent_id", "")),
        "customer_id": str(row.get("customer_id", "")),
        "queue": str(row.get("queue", "")),
        "call_date": row.get("call_date"),
        "speaker": str(row.get("speaker") or ""),
        "start_sec": float(row.get("start_sec", 0.0)),
        "end_sec": float(row.get("end_sec", 0.0)),
        "text": str(row.get("text", "")),
        "score": float(row["score"]) if row.get("score") is not None else None,
        "segment_pos": pos,
        "match_type": match_type,
        "media_type": media_type,
        "original_filename": str(row.get("original_filename") or ""),
    }


def unwrap_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and "rows" in payload:
        rows = payload["rows"]
        return rows if isinstance(rows, list) else []
    if isinstance(payload, list):
        return payload
    return []


def normalize_call_list(payload: Any) -> list[dict[str, Any]]:
    return [normalize_call_summary(row) for row in unwrap_list(payload)]


def normalize_search_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [normalize_search_hit(row) for row in payload]
    return []


def fetch_call_detail(client, base_url: str, call_id: str) -> dict[str, Any]:
    detail_resp = client.get(f"{base_url}/api/calls/{call_id}")
    if detail_resp.status_code == 404:
        return {"id": call_id, "status": "queued", "segments": [], "comments": []}
    detail_resp.raise_for_status()
    detail = detail_resp.json()
    comments_payload = client.get(f"{base_url}/api/comments/call/{call_id}").json()
    comments = unwrap_list(comments_payload)
    return normalize_call_detail(detail, comments)


def upload_pixeltable_fixture(
    client,
    base_url: str,
    *,
    path: Path,
    entry: dict,
    mime: str,
    timeout: float,
) -> str:
    import uuid as _uuid

    call_id = _uuid.uuid4()
    suffix = path.suffix.lower()
    # .webm is audio per shared/call_center_api/constants.py
    is_video = suffix in {".mp4", ".mov", ".mkv"}
    data = {
        "uuid": str(call_id),
        "call_date": entry["call_date"],
        "agent_id": entry["agent_id"],
        "customer_id": entry["customer_id"],
        "queue": entry["queue"],
        "vertical": entry.get("vertical", "call_center"),
        "media_type": "video" if is_video else "audio",
        "original_filename": path.name,
    }
    with path.open("rb") as handle:
        resp = client.post(
            f"{base_url}/api/calls/upload",
            data=data,
            files={"audio": (path.name, handle, mime)},
            timeout=timeout,
        )
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"Upload failed ({base_url}): {resp.status_code} {resp.text}")
    body = resp.json()
    return str(body.get("id") or call_id)


def wait_for_pixeltable_call(client, base_url: str, call_id: str, *, poll_sec: float, timeout_sec: float) -> dict:
    deadline = __import__("time").time() + timeout_sec
    while __import__("time").time() < deadline:
        detail = fetch_call_detail(client, base_url, call_id)
        status = detail.get("status")
        if status == "failed":
            return detail
        if status == "completed":
            seg_count = len(detail.get("segments") or [])
            if seg_count == 0:
                return detail
            embed = client.get(f"{base_url}/api/calls/{call_id}/embed-ready", timeout=10.0)
            if embed.status_code == 200 and embed.json().get("embed_ready"):
                return detail
        __import__("time").sleep(poll_sec)
    raise TimeoutError(f"Timed out waiting for {call_id} on {base_url}")
