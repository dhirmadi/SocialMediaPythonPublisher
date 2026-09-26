"""Add the nullable angle column to pv2_caption_history (PUB-051).

Additive: existing rows keep ``angle IS NULL``, which the content-angle
rotation treats as "never used".

Revision ID: 004
Revises: 003
Create Date: 2026-09-25

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pv2_caption_history", sa.Column("angle", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("pv2_caption_history", "angle")
