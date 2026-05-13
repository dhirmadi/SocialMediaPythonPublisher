"""Create pv2_caption_history table.

Revision ID: 001
Revises: None
Create Date: 2026-05-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pv2_caption_history",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant", sa.String(128), nullable=False),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("caption_text", sa.Text, nullable=False),
        sa.Column("image_filename", sa.String(512), nullable=True),
        sa.Column("image_sha256", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("caption_source", sa.String(32), nullable=False, server_default="ai_generated"),
        sa.Column("was_truncated", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("original_length", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_pv2_caption_history_lookup",
        "pv2_caption_history",
        ["tenant", "platform", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_pv2_caption_history_lookup", table_name="pv2_caption_history")
    op.drop_table("pv2_caption_history")
