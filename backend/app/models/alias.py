from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Alias(Base):
    """Normalized alias rows (`aliases`)."""

    __tablename__ = "aliases"
    __table_args__ = (
        UniqueConstraint(
            "alias_type",
            "scope_value",
            "alias_norm",
            name="ux_aliases_lookup",
        ),
        Index("idx_aliases_canonical", "alias_type", "canonical_value"),
        Index("idx_aliases_active", "alias_type", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    alias_norm: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_value: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
