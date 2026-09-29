"""Add vertical column to calls."""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "003_vertical"
down_revision: Union[str, None] = "002_video_support"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "calls",
        sa.Column("vertical", sa.String(32), nullable=False, server_default="call_center"),
    )


def downgrade() -> None:
    op.drop_column("calls", "vertical")
