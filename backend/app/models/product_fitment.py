"""Vehicle directory ids selected for a product (mock matrix until Base-Auto)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.product import Product


class ProductVehicleFitment(Base):
    """One selected vehicle matrix row per product (directory ids)."""

    __tablename__ = "product_fitments"
    __table_args__ = (
        UniqueConstraint("product_id", name="ux_product_fitments_product"),
        Index("idx_product_fitments_product", "product_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("products.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    make_id: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    product: Mapped["Product"] = relationship(
        "Product",
        back_populates="vehicle_fitment",
        uselist=False,
    )
