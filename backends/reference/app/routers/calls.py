"""Call upload, list, detail, KPIs, flagged, and delete endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session, joinedload

from call_center_api.enrichment import has_negative_sentiment_moments
from call_center_api.verticals import normalize_vertical
from app.database import get_db
from app.models import Call, TranscriptSegment
from call_center_api.constants import FLAGGED_SENTIMENT_THRESHOLD
from call_center_api.schemas import CallDetail, CallSummary, CallUploadResponse, CommentOut, KpiResponse, SegmentOut
from app.services.storage import delete_upload_files, save_upload
from worker.tasks.process_call import process_call

router = APIRouter(prefix="/api/calls", tags=["calls"])


def _sentiment_fields(call: Call) -> tuple[str | None, float | None]:
    if not call.sentiment or not isinstance(call.sentiment, dict):
        return None, None
    label = call.sentiment.get("label")
    score = call.sentiment.get("score")
    try:
        score_f = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_f = None
    return str(label) if label else None, score_f


def _to_summary(call: Call) -> CallSummary:
    label, score = _sentiment_fields(call)
    media_type = call.media_type if call.media_type in ("audio", "video") else "audio"
    return CallSummary(
        id=call.id,
        call_date=call.call_date,
        agent_id=call.agent_id,
        customer_id=call.customer_id,
        queue=call.queue,
        vertical=call.vertical or "call_center",
        duration_sec=call.duration_sec,
        handle_time_sec=call.handle_time_sec,
        status=call.status,
        category=call.category,
        summary=call.summary,
        sentiment_label=label,
        sentiment_score=score,
        media_type=media_type,  # type: ignore[arg-type]
        has_video_source=bool(call.video_path),
    )


@router.post("/upload", response_model=CallUploadResponse, status_code=202)
async def upload_call(
    audio: UploadFile = File(...),
    call_date: datetime = Form(...),
    agent_id: str = Form(...),
    customer_id: str = Form(...),
    queue: str = Form(...),
    vertical: str = Form(default="call_center"),
    db: Session = Depends(get_db),
):
    call_id = uuid.uuid4()
    try:
        audio_path, original_filename, video_path, media_type = save_upload(audio, call_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    call = Call(
        id=call_id,
        audio_path=audio_path,
        original_filename=original_filename,
        video_path=video_path,
        media_type=media_type,
        call_date=call_date,
        agent_id=agent_id,
        customer_id=customer_id,
        queue=queue,
        vertical=normalize_vertical(vertical),
        status="queued",
    )
    db.add(call)
    db.commit()
    db.refresh(call)

    process_call.delay(str(call.id))
    return CallUploadResponse(id=call.id, status=call.status)


@router.get("", response_model=list[CallSummary])
def list_calls(
    agent_id: str | None = None,
    queue: str | None = None,
    sentiment_label: str | None = None,
    min_handle_time: float | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(Call).order_by(Call.call_date.desc()).limit(min(limit, 200))
    if agent_id:
        q = q.filter(Call.agent_id == agent_id)
    if queue:
        q = q.filter(Call.queue == queue)
    if min_handle_time is not None:
        q = q.filter(Call.handle_time_sec >= min_handle_time)

    calls = q.all()
    results = [_to_summary(c) for c in calls]
    if sentiment_label:
        results = [c for c in results if c.sentiment_label == sentiment_label]
    return results


@router.get("/kpis", response_model=KpiResponse)
def get_kpis(db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=7)
    calls = db.query(Call).filter(Call.call_date >= since, Call.status == "completed").all()
    if not calls:
        return KpiResponse(call_count=0, avg_handle_time_sec=0.0, avg_sentiment_score=0.0)

    handle_times = [c.handle_time_sec for c in calls if c.handle_time_sec is not None]
    scores = []
    for c in calls:
        _, score = _sentiment_fields(c)
        if score is not None:
            scores.append(score)

    return KpiResponse(
        call_count=len(calls),
        avg_handle_time_sec=sum(handle_times) / len(handle_times) if handle_times else 0.0,
        avg_sentiment_score=sum(scores) / len(scores) if scores else 0.0,
    )


@router.get("/flagged", response_model=list[CallSummary])
def flagged_calls(limit: int = 50, db: Session = Depends(get_db)):
    calls = db.query(Call).filter(Call.status == "completed").order_by(Call.call_date.desc()).limit(200).all()
    flagged: list[CallSummary] = []
    for call in calls:
        label, score = _sentiment_fields(call)
        if label == "negative" or (score is not None and score < FLAGGED_SENTIMENT_THRESHOLD):
            flagged.append(_to_summary(call))
        elif has_negative_sentiment_moments(call.sentiment if isinstance(call.sentiment, dict) else None):
            flagged.append(_to_summary(call))
        if len(flagged) >= limit:
            break
    return flagged


@router.get("/{call_id}", response_model=CallDetail)
def get_call(call_id: uuid.UUID, db: Session = Depends(get_db)):
    call = (
        db.query(Call)
        .options(joinedload(Call.segments), joinedload(Call.comments))
        .filter(Call.id == call_id)
        .first()
    )
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    media_type = call.media_type if call.media_type in ("audio", "video") else "audio"
    return CallDetail(
        id=call.id,
        audio_path=f"/api/calls/{call.id}/audio",
        original_filename=call.original_filename,
        call_date=call.call_date,
        agent_id=call.agent_id,
        customer_id=call.customer_id,
        queue=call.queue,
        vertical=call.vertical or "call_center",
        duration_sec=call.duration_sec,
        handle_time_sec=call.handle_time_sec,
        status=call.status,
        category=call.category,
        summary=call.summary,
        action_items=call.action_items,
        sentiment=call.sentiment,
        qa_scorecard=call.qa_scorecard,
        error_message=call.error_message,
        segments=[SegmentOut.model_validate(s) for s in call.segments],
        comments=[CommentOut.model_validate(c) for c in call.comments],
        media_type=media_type,  # type: ignore[arg-type]
        has_video_source=bool(call.video_path),
    )


@router.get("/{call_id}/audio")
def get_call_audio(call_id: uuid.UUID, db: Session = Depends(get_db)):
    from pathlib import Path

    from fastapi.responses import FileResponse

    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    path = Path(call.audio_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(path, filename=call.original_filename)


@router.get("/{call_id}/video")
def get_call_video(call_id: uuid.UUID, db: Session = Depends(get_db)):
    from pathlib import Path

    from fastapi.responses import FileResponse

    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    if not call.video_path:
        raise HTTPException(status_code=404, detail="Video not available for this call")
    path = Path(call.video_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(path, filename=call.original_filename)


@router.delete("/{call_id}", status_code=204)
def delete_call(call_id: uuid.UUID, db: Session = Depends(get_db)):
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    delete_upload_files(call.audio_path, call.video_path)
    db.delete(call)
    db.commit()
