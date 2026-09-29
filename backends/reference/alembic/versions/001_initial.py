"""Initial schema with pgvector."""

from typing import Sequence, Union

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("audio_path", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("call_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.String(128), nullable=False),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("queue", sa.String(128), nullable=False),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("handle_time_sec", sa.Float(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("category", sa.String(256), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("action_items", postgresql.JSONB(), nullable=True),
        sa.Column("sentiment", postgresql.JSONB(), nullable=True),
        sa.Column("qa_scorecard", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "transcript_segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id", ondelete="CASCADE")),
        sa.Column("speaker", sa.String(32), nullable=False),
        sa.Column("start_sec", sa.Float(), nullable=False),
        sa.Column("end_sec", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("pos", sa.Integer(), nullable=False),
    )

    op.create_table(
        "coaching_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id", ondelete="CASCADE")),
        sa.Column(
            "segment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("transcript_segments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("start_sec", sa.Float(), nullable=False),
        sa.Column("author", sa.String(128), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_index("ix_calls_call_date", "calls", ["call_date"])
    op.create_index("ix_segments_call_id", "transcript_segments", ["call_id"])
    op.execute(
        "CREATE INDEX ix_segments_embedding ON transcript_segments "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_segments_embedding", table_name="transcript_segments")
    op.drop_index("ix_segments_call_id", table_name="transcript_segments")
    op.drop_index("ix_calls_call_date", table_name="calls")
    op.drop_table("coaching_comments")
    op.drop_table("transcript_segments")
    op.drop_table("calls")
