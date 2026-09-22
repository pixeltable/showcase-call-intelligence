from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Call, TranscriptSegment
from app.services.ollama_client import OllamaClient
from worker.celery_app import celery_app
from worker.tasks.embed_maintenance import embed_call_segments


def _transcript_from_segments(segments: list[TranscriptSegment]) -> str:
    parts: list[str] = []
    for seg in segments:
        parts.append(f"[{seg.start_sec:.1f}s-{seg.end_sec:.1f}s] {seg.speaker}: {seg.text}")
    return "\n".join(parts)


def enrich_and_complete_call(db: Session, call: Call) -> None:
    segments = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.call_id == call.id)
        .order_by(TranscriptSegment.pos)
        .all()
    )
    if not segments:
        raise ValueError(f"Call {call.id} has no transcript segments")

    if not call.summary:
        call.status = "enriching"
        call.error_message = None
        db.commit()

        client = OllamaClient()
        result = client.enrich_call(
            _transcript_from_segments(segments),
            vertical=call.vertical or "call_center",
        )
        call.summary = result.summary
        call.action_items = result.action_items
        call.sentiment = result.sentiment
        call.category = result.category
        call.qa_scorecard = result.qa_scorecard

    call.status = "embedding"
    call.error_message = None
    db.commit()

    needs_embed = any(
        segment.text.strip() and segment.embedding is None
        for segment in segments
    )
    if needs_embed:
        embed_call_segments(db, call.id)
    else:
        db.commit()

    call.status = "completed"
    call.error_message = None
    db.commit()


@celery_app.task(
    name="worker.tasks.resume_call_processing",
    soft_time_limit=settings.celery_task_soft_time_limit_sec,
    time_limit=settings.celery_task_time_limit_sec,
)
def resume_call_processing(call_id: str) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        call = db.get(Call, uuid.UUID(call_id))
        if not call:
            return
        if call.status == "completed":
            return

        segment_count = (
            db.query(TranscriptSegment).filter(TranscriptSegment.call_id == call.id).count()
        )
        if segment_count == 0:
            raise ValueError(f"Call {call_id} has no transcript segments to resume from")

        enrich_and_complete_call(db, call)
    except Exception as exc:
        db.rollback()
        call = db.get(Call, uuid.UUID(call_id))
        if call:
            call.status = "failed"
            call.error_message = str(exc)
            db.commit()
        raise exc
    finally:
        db.close()
