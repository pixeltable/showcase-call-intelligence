from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import TranscriptSegment
from app.services.embed_service import embed_texts
from worker.celery_app import celery_app


def _apply_embeddings(segments: list[TranscriptSegment], texts: list[str]) -> None:
    if not texts:
        return
    try:
        vectors = embed_texts(texts)
    except Exception as exc:
        for segment in segments:
            segment.embedding = None
        raise RuntimeError(f"Embedding failed: {exc}") from exc
    for segment, vector in zip(segments, vectors, strict=True):
        segment.embedding = vector


def embed_call_segments(db: Session, call_id: uuid.UUID) -> None:
    segments = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.call_id == call_id)
        .order_by(TranscriptSegment.pos)
        .all()
    )
    embeddable = [(segment, segment.text) for segment in segments if segment.text.strip()]
    if embeddable:
        _apply_embeddings([s for s, _ in embeddable], [t for _, t in embeddable])
    db.commit()


def reembed_call_segments(db: Session, call_id: uuid.UUID) -> int:
    """Embed segments that still have NULL embeddings. Returns count updated."""
    segments = (
        db.query(TranscriptSegment)
        .filter(TranscriptSegment.call_id == call_id, TranscriptSegment.embedding.is_(None))
        .order_by(TranscriptSegment.pos)
        .all()
    )
    embeddable = [(segment, segment.text) for segment in segments if segment.text.strip()]
    if not embeddable:
        return 0
    _apply_embeddings([s for s, _ in embeddable], [t for _, t in embeddable])
    updated = sum(1 for segment, _ in embeddable if segment.embedding is not None)
    if updated:
        db.commit()
    return updated


@celery_app.task(name="worker.tasks.reembed_call")
def reembed_call(call_id: str) -> int:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        return reembed_call_segments(db, uuid.UUID(call_id))
    finally:
        db.close()


@celery_app.task(name="worker.tasks.backfill_embeddings")
def backfill_embeddings(limit: int = 100) -> int:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        segments = (
            db.query(TranscriptSegment)
            .filter(TranscriptSegment.embedding.is_(None))
            .order_by(TranscriptSegment.call_id, TranscriptSegment.pos)
            .limit(limit)
            .all()
        )
        embeddable = [(segment, segment.text) for segment in segments if segment.text.strip()]
        if not embeddable:
            return 0
        _apply_embeddings([s for s, _ in embeddable], [t for _, t in embeddable])
        updated = sum(1 for segment, _ in embeddable if segment.embedding is not None)
        if updated:
            db.commit()
        return updated
    finally:
        db.close()
