from __future__ import annotations

from sqlalchemy import Boolean, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CategoryMapping(Base):
    """
    Pattern-based category mapping (`category_mapping`).
    Column `ms_folder_path` is exposed as `folder_path` in Python (legacy DB name).
    """

    __tablename__ = "category_mapping"
    __table_args__ = (
        UniqueConstraint("part_type_pattern", name="ux_catmap_pattern"),
        Index("idx_catmap_priority", "is_active", "priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    part_type_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    folder_path: Mapped[str] = mapped_column("ms_folder_path", Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
