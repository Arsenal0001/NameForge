"""Local cache tables for Odoo catalog snapshots (fast UI / offline reads)."""

from __future__ import annotations

from sqlalchemy import Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OdooCategory(Base):
    """Mirror of ``product.category`` rows touched during sync."""

    __tablename__ = "odoo_categories"

    odoo_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    complete_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    naming_template_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[str] = mapped_column(Text, nullable=False)


class OdooProductAttribute(Base):
    """Mirror of ``product.attribute``."""

    __tablename__ = "odoo_product_attributes"

    odoo_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    create_variant: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[str] = mapped_column(Text, nullable=False)


class OdooProductAttributeValue(Base):
    """Mirror of ``product.attribute.value``."""

    __tablename__ = "odoo_product_attribute_values"

    odoo_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attribute_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[str] = mapped_column(Text, nullable=False)


class OdooProductTemplate(Base):
    """Mirror of ``product.template`` fields needed for PIM workflows."""

    __tablename__ = "odoo_product_templates"

    odoo_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    default_code: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    categ_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    attribute_line_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    synced_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (Index("idx_odoo_tpl_name", "name"),)
