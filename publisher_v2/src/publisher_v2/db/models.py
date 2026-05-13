"""SQLAlchemy ORM models for Publisher V2.

All tables use the ``pv2_`` prefix to avoid collisions with the orchestrator
tables in the shared Postgres instance.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all Publisher V2 tables."""


class CaptionHistory(Base):
    """Persisted caption history for anti-repetition and analytics."""

    __tablename__ = "pv2_caption_history"

    # Integer for SQLite compat in tests; Alembic migration uses BigInteger for Postgres.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    caption_text: Mapped[str] = mapped_column(Text, nullable=False)
    image_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_sha256: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    caption_source: Mapped[str] = mapped_column(String(32), nullable=False, default="ai_generated")
    was_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    original_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_pv2_caption_history_lookup", "tenant", "platform", created_at.desc()),)

    def __repr__(self) -> str:
        return (
            f"<CaptionHistory(id={self.id}, tenant={self.tenant!r}, "
            f"platform={self.platform!r}, len={len(self.caption_text)})>"
        )
