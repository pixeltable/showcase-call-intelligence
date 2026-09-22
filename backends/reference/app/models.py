import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from call_center_api.constants import EMBED_DIM


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    audio_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    media_type: Mapped[str] = mapped_column(String(16), nullable=False, default="audio")
    video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    call_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    queue: Mapped[str] = mapped_column(String(128), nullable=False)
    vertical: Mapped[str] = mapped_column(String(32), nullable=False, default="call_center", server_default="call_center")
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    handle_time_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    category: Mapped[str | None] = mapped_column(String(256), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_items: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sentiment: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    qa_scorecard: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="call", cascade="all, delete-orphan", order_by="TranscriptSegment.pos"
    )
    comments: Mapped[list["CoachingComment"]] = relationship(
        back_populates="call", cascade="all, delete-orphan"
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"))
    speaker: Mapped[str] = mapped_column(String(32), nullable=False)
    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    pos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    call: Mapped["Call"] = relationship(back_populates="segments")
    comments: Mapped[list["CoachingComment"]] = relationship(back_populates="segment")


class CoachingComment(Base):
    __tablename__ = "coaching_comments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"))
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcript_segments.id", ondelete="SET NULL"), nullable=True
    )
    start_sec: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    author: Mapped[str] = mapped_column(String(128), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    call: Mapped["Call"] = relationship(back_populates="comments")
    segment: Mapped["TranscriptSegment | None"] = relationship(back_populates="comments")
