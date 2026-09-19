"""Create pv2_publish_record table (#85).

Revision ID: 002
Revises: 001
Create Date: 2026-09-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pv2_publish_record",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tenant", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="leased"),
        sa.Column("post_id", sa.String(256), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("leased_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant", "content_hash", "platform", name="uq_pv2_publish_record_key"),
    )
    op.create_index(
        "ix_pv2_publish_record_lookup",
        "pv2_publish_record",
        ["tenant", "content_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_pv2_publish_record_lookup", table_name="pv2_publish_record")
    op.drop_table("pv2_publish_record")
