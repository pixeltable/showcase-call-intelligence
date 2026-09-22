"""Coaching comment endpoints — native catalog shape."""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone

import queries
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/comments", tags=["comments"])


class CommentCreate(BaseModel):
    call_uuid: _uuid.UUID
    segment_pos: int = Field(default=-1, ge=-1)
    start_sec: float = 0.0
    author: str = Field(min_length=1, max_length=128)
    comment: str = Field(min_length=1)


@router.get("/call/{call_uuid}")
def list_comments(call_uuid: _uuid.UUID):
    rows = queries.collect_query(queries.comments_for_call, call_uuid=call_uuid)
    return {"rows": rows}


@router.post("", status_code=201)
def create_comment(payload: CommentCreate):
    calls = queries.calls
    existing = calls.where(calls.uuid == payload.call_uuid).select(calls.uuid, calls.segments).collect()
    if existing is None or len(existing) == 0:
        raise HTTPException(status_code=404, detail="Call not found")

    segment_pos = payload.segment_pos
    if segment_pos >= 0:
        row = existing[0]
        segments = row.get("segments")
        seg_count = len(segments) if isinstance(segments, list) else 0
        if segment_pos >= seg_count:
            raise HTTPException(status_code=400, detail="Invalid segment for call")

    comments = queries.comments
    status = comments.insert(
        [
            {
                "call_uuid": payload.call_uuid,
                "segment_pos": segment_pos,
                "start_sec": payload.start_sec,
                "author": payload.author,
                "comment": payload.comment,
                "timestamp": datetime.now(timezone.utc),
            }
        ],
        return_rows=True,
    )
    if not status.rows:
        raise HTTPException(status_code=500, detail="Failed to save comment")
    row = status.rows[0]
    return {
        "uuid": row["uuid"],
        "call_uuid": payload.call_uuid,
        "segment_pos": segment_pos if segment_pos >= 0 else None,
        "start_sec": float(row.get("start_sec", 0.0)),
        "author": str(row.get("author", "")),
        "comment": str(row.get("comment", "")),
        "timestamp": row.get("timestamp") or datetime.now(timezone.utc),
    }
