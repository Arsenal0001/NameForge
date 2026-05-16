from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PartTypeFolderMap(Base):
    """Legacy part-type → folder path map (`part_type_folder_map`)."""

    __tablename__ = "part_type_folder_map"

    part_type: Mapped[str] = mapped_column(Text, primary_key=True)
    folder_path: Mapped[str] = mapped_column("ms_folder_path", Text, nullable=False)
    created_at: Mapped[str | None] = mapped_column(Text, nullable=True)
