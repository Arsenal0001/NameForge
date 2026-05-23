from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKeyConstraint, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.fitment import Fitment
    from app.models.product_fitment import ProductVehicleFitment


class Product(Base):
    """
    Cached product row (`products`).
    Python attribute `odoo_product_id` maps to legacy DB column `ms_product_id`
    (unchanged SQLite schema).
    """

    __tablename__ = "products"
    __table_args__ = (
        ForeignKeyConstraint(
            ["template_key", "template_version"],
            ["templates.template_key", "templates.version"],
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        Index("idx_products_article", "article"),
        Index("idx_products_brand", "brand"),
        Index("idx_products_brand_article", "brand", "article"),
        Index("idx_products_generation_status", "generation_status"),
        Index("idx_products_applicability_type", "applicability_type"),
        Index("idx_products_template", "template_key", "template_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    odoo_product_id: Mapped[str] = mapped_column(
        "ms_product_id",
        Text,
        nullable=False,
        unique=True,
    )
    external_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    article: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str] = mapped_column(Text, nullable=False)
    part_type: Mapped[str] = mapped_column(Text, nullable=False)
    applicability_type: Mapped[str] = mapped_column(Text, nullable=False)
    side_axis: Mapped[str | None] = mapped_column(Text, nullable=True)
    cross_numbers: Mapped[str | None] = mapped_column(Text, nullable=True)
    supplier_raw_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_make: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    year_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    year_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engine: Mapped[str | None] = mapped_column(Text, nullable=True)
    fitment_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_key: Mapped[str] = mapped_column(Text, nullable=False)
    template_version: Mapped[str] = mapped_column(Text, nullable=False)
    generation_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="new"
    )
    name_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generated_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribute_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    product_folder: Mapped[str | None] = mapped_column(Text, nullable=True)

    fitments: Mapped[list["Fitment"]] = relationship(
        "Fitment",
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )
    vehicle_fitment: Mapped["ProductVehicleFitment | None"] = relationship(
        "ProductVehicleFitment",
        back_populates="product",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
        lazy="selectin",
    )
