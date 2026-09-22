"""Add video support columns to calls."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_video_support"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("media_type", sa.String(16), nullable=False, server_default="audio"))
    op.add_column("calls", sa.Column("video_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("calls", "video_path")
    op.drop_column("calls", "media_type")
