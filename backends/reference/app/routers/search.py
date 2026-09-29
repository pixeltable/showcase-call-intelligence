"""Hybrid keyword and semantic search over transcript segments."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Call, TranscriptSegment
from app.services.embed_service import embed_text
from call_center_api.schemas import SearchHit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/search", tags=["search"])


def _like_contains(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _search_hit(
    segment: TranscriptSegment,
    call: Call,
    *,
    score: float | None,
    match_type: str,
) -> SearchHit:
    media_type = call.media_type if call.media_type in ("audio", "video") else "audio"
    return SearchHit(
        call_id=call.id,
        segment_id=segment.id,
        agent_id=call.agent_id,
        customer_id=call.customer_id,
        queue=call.queue,
        call_date=call.call_date,
        speaker=segment.speaker,
        start_sec=segment.start_sec,
        end_sec=segment.end_sec,
        text=segment.text,
        score=score,
        segment_pos=segment.pos,
        match_type=match_type,  # type: ignore[arg-type]
        media_type=media_type,  # type: ignore[arg-type]
        original_filename=call.original_filename or "",
    )


@router.get("", response_model=list[SearchHit])
def search_transcripts(
    q: str = Query(min_length=1, max_length=500),
    mode: str = Query(default="hybrid", pattern="^(keyword|semantic|hybrid)$"),
    limit: int = Query(default=20, le=100),
    db: Session = Depends(get_db),
):
    query = q.strip()
    hits: list[SearchHit] = []
    seen: set[tuple[str, str]] = set()

    if mode in ("keyword", "hybrid"):
        keyword_rows = (
            db.query(TranscriptSegment, Call)
            .join(Call, Call.id == TranscriptSegment.call_id)
            .filter(
                Call.status == "completed",
                TranscriptSegment.text.ilike(_like_contains(query), escape="\\"),
            )
            .order_by(Call.call_date.desc())
            .limit(limit)
            .all()
        )
        for segment, call in keyword_rows:
            key = (str(call.id), str(segment.id))
            if key in seen:
                continue
            seen.add(key)
            hits.append(_search_hit(segment, call, score=1.0, match_type="keyword"))

    if mode in ("semantic", "hybrid") and len(hits) < limit:
        try:
            embedding = embed_text(query)
            distance = TranscriptSegment.embedding.cosine_distance(embedding)
            semantic_rows = (
                db.query(TranscriptSegment, Call, distance)
                .join(Call, Call.id == TranscriptSegment.call_id)
                .filter(
                    Call.status == "completed",
                    TranscriptSegment.embedding.isnot(None),
                )
                .order_by(distance)
                .limit(limit)
                .all()
            )

            for segment, call, dist in semantic_rows:
                key = (str(call.id), str(segment.id))
                if key in seen:
                    continue
                seen.add(key)
                hits.append(_search_hit(segment, call, score=1.0 - float(dist), match_type="semantic"))
        except Exception as exc:
            logger.warning("Semantic search failed for query=%r: %s", query, exc)

    return hits[:limit]
