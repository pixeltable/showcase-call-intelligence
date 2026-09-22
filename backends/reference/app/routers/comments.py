"""Coaching comment endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Call, CoachingComment, TranscriptSegment
from call_center_api.schemas import CommentCreate, CommentOut

router = APIRouter(prefix="/api/comments", tags=["comments"])


@router.post("", response_model=CommentOut, status_code=201)
def create_comment(payload: CommentCreate, db: Session = Depends(get_db)):
    call = db.get(Call, payload.call_id)
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    segment = None
    if payload.segment_id:
        segment = db.get(TranscriptSegment, payload.segment_id)
        if not segment or segment.call_id != call.id:
            raise HTTPException(status_code=400, detail="Invalid segment for call")

    comment = CoachingComment(
        call_id=payload.call_id,
        segment_id=payload.segment_id,
        start_sec=payload.start_sec,
        author=payload.author,
        comment=payload.comment,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return CommentOut.model_validate(comment)


@router.get("/call/{call_id}", response_model=list[CommentOut])
def list_comments(call_id: uuid.UUID, db: Session = Depends(get_db)):
    comments = (
        db.query(CoachingComment)
        .filter(CoachingComment.call_id == call_id)
        .order_by(CoachingComment.created_at.asc())
        .all()
    )
    return [CommentOut.model_validate(c) for c in comments]
