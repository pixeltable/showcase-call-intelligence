import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CallUploadResponse(BaseModel):
    id: uuid.UUID
    status: str


class SegmentOut(BaseModel):
    id: uuid.UUID
    speaker: str
    start_sec: float
    end_sec: float
    text: str
    pos: int

    model_config = {"from_attributes": True}


class CommentOut(BaseModel):
    id: uuid.UUID
    call_id: uuid.UUID
    segment_id: uuid.UUID | None
    start_sec: float
    author: str
    comment: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CommentCreate(BaseModel):
    call_id: uuid.UUID
    segment_id: uuid.UUID | None = None
    start_sec: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    author: str = Field(min_length=1, max_length=128)
    comment: str = Field(min_length=1, max_length=10000)


class CallSummary(BaseModel):
    id: uuid.UUID
    call_date: datetime
    agent_id: str
    customer_id: str
    queue: str
    vertical: str = "call_center"
    duration_sec: float | None
    handle_time_sec: float | None
    status: str
    category: str | None
    summary: str | None
    sentiment_label: str | None = None
    sentiment_score: float | None = None
    media_type: Literal["audio", "video"] = "audio"
    has_video_source: bool = False

    model_config = {"from_attributes": True}


class CallDetail(BaseModel):
    id: uuid.UUID
    audio_path: str
    original_filename: str
    call_date: datetime
    agent_id: str
    customer_id: str
    queue: str
    vertical: str = "call_center"
    duration_sec: float | None
    handle_time_sec: float | None
    status: str
    category: str | None
    summary: str | None
    action_items: list | dict | None
    sentiment: dict | None
    qa_scorecard: dict | None
    error_message: str | None
    segments: list[SegmentOut]
    comments: list[CommentOut]
    media_type: Literal["audio", "video"] = "audio"
    has_video_source: bool = False

    model_config = {"from_attributes": True}


class KpiResponse(BaseModel):
    call_count: int
    avg_handle_time_sec: float
    avg_sentiment_score: float


class SearchHit(BaseModel):
    call_id: uuid.UUID
    segment_id: uuid.UUID
    agent_id: str
    customer_id: str
    queue: str
    call_date: datetime
    speaker: str
    start_sec: float
    end_sec: float
    text: str
    score: float | None = None
    segment_pos: int = 0
    match_type: Literal["keyword", "semantic"] = "keyword"
    media_type: Literal["audio", "video"] = "audio"
    original_filename: str = ""


class HealthCheckResult(BaseModel):
    ok: bool
    detail: str | None = None

    model_config = {"extra": "allow"}


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    backend: Literal["reference", "pixeltable"]
    checks: dict[str, HealthCheckResult]
