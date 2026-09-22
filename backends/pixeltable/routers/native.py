"""Native Pixeltable FastAPIRouter — declarative @pxt.query routes."""

from __future__ import annotations

import logging
import shutil
import uuid as _uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
import queries
from call_center_api.constants import ALLOWED_UPLOAD_EXTENSIONS, ALLOWED_VIDEO_EXTENSIONS
from call_center_api.verticals import normalize_vertical
from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pixeltable.serving import FastAPIRouter

logger = logging.getLogger(__name__)

router = FastAPIRouter(prefix="/api/calls", tags=["calls"])
comments_table = queries.comments
# Serial inserts avoid catalog lock contention when computed columns start.
_upload_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pxt-upload")


def _insert_call_row(row: dict) -> None:
    try:
        status = queries.calls.insert([row], on_error="ignore")
        if status.num_rows != 1:
            logger.error("Pixeltable insert incomplete for call %s: got %s rows", row.get("uuid"), status.num_rows)
    except Exception:
        logger.exception("Pixeltable insert failed for call %s", row.get("uuid"))


@router.post("/upload", status_code=202)
async def upload_call(
    audio: UploadFile = File(...),
    uuid: _uuid.UUID = Form(...),
    call_date: datetime = Form(...),
    agent_id: str = Form(...),
    customer_id: str = Form(...),
    queue: str = Form(...),
    vertical: str = Form(default="call_center"),
    media_type: str = Form(default="audio"),
    original_filename: str | None = Form(default=None),
):
    """Multipart upload — single file field (reference-compatible) mapped to audio/video columns."""
    suffix = Path(original_filename or audio.filename or "upload.wav").suffix.lower() or ".wav"
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    audio.file.seek(0, 2)
    size_bytes = audio.file.tell()
    audio.file.seek(0)
    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(status_code=400, detail=f"File exceeds {config.MAX_UPLOAD_MB}MB limit")

    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = config.UPLOAD_DIR / f"{uuid}{suffix}"
    with dest_path.open("wb") as dest:
        shutil.copyfileobj(audio.file, dest)

    is_video = media_type == "video" or suffix in ALLOWED_VIDEO_EXTENSIONS
    row: dict = {
        "uuid": uuid,
        "call_date": call_date,
        "agent_id": agent_id,
        "customer_id": customer_id,
        "queue": queue,
        "vertical": normalize_vertical(vertical),
        "duration_sec": None,
        "media_type": "video" if is_video else "audio",
        "original_filename": original_filename or audio.filename or f"recording{suffix}",
    }
    if is_video:
        row["video"] = str(dest_path.resolve())
        row["audio"] = None
    else:
        row["audio"] = str(dest_path.resolve())
        row["video"] = None

    _upload_executor.submit(_insert_call_row, row)
    return {"id": str(uuid), "status": "queued"}

router.add_query_route(path="", query=queries.list_calls, method="get")
router.add_query_route(path="/flagged", query=queries.flagged_calls, method="get")


@router.get("/kpis")
def get_kpis():
    """Weekly KPI aggregates — expression query + Python reduce (native catalog fields)."""
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    rows = list(
        queries.calls.where(
            (queries.calls.call_date >= week_ago) & (queries.calls.pipeline_status == "completed")
        )
        .select(
            sentiment=queries.calls.sentiment,
            handle_time_sec=queries.calls.handle_time_sec,
        )
        .collect()
    )
    if not rows:
        return {"call_count": 0, "avg_handle_time_sec": 0.0, "avg_sentiment_score": 0.0}

    handle_times = [float(r["handle_time_sec"]) for r in rows if r.get("handle_time_sec") is not None]
    scores: list[float] = []
    for row in rows:
        sentiment = row.get("sentiment")
        if isinstance(sentiment, dict) and sentiment.get("score") is not None:
            try:
                scores.append(float(sentiment["score"]))
            except (TypeError, ValueError):
                pass

    return {
        "call_count": len(rows),
        "avg_handle_time_sec": sum(handle_times) / len(handle_times) if handle_times else 0.0,
        "avg_sentiment_score": sum(scores) / len(scores) if scores else 0.0,
    }


def _one_row(query_fn, **kwargs) -> dict:
    rows = queries.collect_query(query_fn, **kwargs)
    if not rows:
        raise HTTPException(status_code=404, detail="Call not found")
    if len(rows) > 1:
        raise HTTPException(status_code=409, detail="Multiple rows returned")
    return rows[0]


@router.get("/{uuid}/embed-ready")
def embed_ready(uuid: _uuid.UUID):
    call = _one_row(queries.get_call, uuid=uuid)
    segments_list = call.get("segments") or []
    seg_count = len(segments_list)
    if seg_count == 0:
        return {"embed_ready": True, "segment_count": 0, "view_count": 0}
    view_rows = list(
        queries.segments.where(queries.segments.uuid == uuid).select(queries.segments.text).collect()
    )
    view_count = len(view_rows)
    return {"embed_ready": view_count >= seg_count, "segment_count": seg_count, "view_count": view_count}


@router.get("/{uuid}")
def get_call(uuid: _uuid.UUID):
    return _one_row(queries.get_call, uuid=uuid)


@router.get("/{uuid}/audio")
def get_call_audio(uuid: _uuid.UUID):
    row = _one_row(queries.call_playback_audio, uuid=uuid)
    media = row.get("media")
    if media is None:
        raise HTTPException(status_code=404, detail="Audio not available yet")
    path = Path(str(media))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found on disk")
    return FileResponse(path, filename=path.name)


@router.get("/{uuid}/video")
def get_call_video(uuid: _uuid.UUID):
    row = _one_row(queries.call_playback_video, uuid=uuid)
    media = row.get("media")
    if media is None:
        raise HTTPException(status_code=404, detail="Video not available for this call")
    path = Path(str(media))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found on disk")
    detail = _one_row(queries.get_call, uuid=uuid)
    filename = str(detail.get("original_filename") or path.name)
    return FileResponse(path, filename=filename)


@router.delete("/{call_id}", status_code=204)
def delete_call(call_id: _uuid.UUID):
    calls = queries.calls
    existing = list(calls.where(calls.uuid == call_id).select(calls.uuid).collect())
    if not existing:
        raise HTTPException(status_code=404, detail="Call not found")
    comments_table.delete(comments_table.call_uuid == call_id)
    calls.delete(calls.uuid == call_id)
