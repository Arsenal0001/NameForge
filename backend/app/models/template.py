from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Template(Base):
    """
    Naming template row (`templates`).
    Composite (`template_key`, `version`) is referenced by `products`.
    """

    __tablename__ = "templates"
    __table_args__ = (
        UniqueConstraint("template_key", "version", name="uq_templates_key_version"),
        Index("idx_templates_key_active", "template_key", "is_active"),
        Index(
            "idx_templates_part_type",
            "part_type_trigger",
            sqlite_where=text("part_type_trigger IS NOT NULL"),
            postgresql_where=text("part_type_trigger IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    applicability_type: Mapped[str] = mapped_column(Text, nullable=False)
    name_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    part_type_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    part_type_trigger: Mapped[str | None] = mapped_column(Text, nullable=True)
