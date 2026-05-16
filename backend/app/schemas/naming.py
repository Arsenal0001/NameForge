"""Pydantic models for the naming engine (inputs / outputs)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FitmentNamingInput(BaseModel):
    """Single fitment row used for naming / hashing."""

    model_config = ConfigDict(str_strip_whitespace=True)

    make: str = ""
    model: str = ""
    body: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    engine: str | None = None
    is_primary: bool = False

    @field_validator("year_from", "year_to", mode="before")
    @classmethod
    def _empty_int_none(cls, v: object) -> object:
        if v == "":
            return None
        return v

    @model_validator(mode="after")
    def _hierarchy_make_model_body(self) -> FitmentNamingInput:
        mk = self.make.strip()
        md = self.model.strip()
        bd = (self.body or "").strip()
        if md and not mk:
            raise ValueError("Применяемость: модель без марки (Марка → Модель → Поколение)")
        if bd and not md:
            raise ValueError("Применяемость: поколение/кузов без модели")
        return self


class ProductNamingInput(BaseModel):
    """Product-side fields used for naming (aligned with ``products`` + optional Odoo-like extras)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    part_type: str
    brand: str = ""
    article: str = ""
    applicability_type: Literal["fitment", "universal"] = "universal"
    template_key: str = ""
    template_version: str = ""
    side_axis: str | None = None
    cross_numbers: str | None = None
    primary_make: str | None = None
    primary_model: str | None = None
    primary_body: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    engine: str | None = None
    installation_location: str | None = Field(
        default=None,
        description="Место установки (стандартное текстовое поле Odoo / PIM), опционально.",
    )
    characteristic_parts: list[str] = Field(
        default_factory=list,
        description="Доп. характеристики для названия (порядок сохраняется).",
    )
    supplier_raw_name: str | None = Field(
        default=None,
        description="Сырой текст названия от поставщика (только для search_keywords).",
    )

    @field_validator("year_from", "year_to", mode="before")
    @classmethod
    def _empty_int_none(cls, v: object) -> object:
        if v == "":
            return None
        return v

    @field_validator("characteristic_parts", mode="before")
    @classmethod
    def _normalize_parts(cls, v: object) -> object:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("characteristic_parts", mode="after")
    @classmethod
    def _strip_parts(cls, v: list[str]) -> list[str]:
        return [str(x).strip() for x in v if str(x).strip()]

    @model_validator(mode="after")
    def _primary_hierarchy(self) -> ProductNamingInput:
        if self.applicability_type != "fitment":
            return self
        mk = (self.primary_make or "").strip()
        md = (self.primary_model or "").strip()
        bd = (self.primary_body or "").strip()
        if md and not mk:
            raise ValueError("Primary: модель без марки")
        if bd and not md:
            raise ValueError("Primary: поколение без модели")
        return self


class GeneratedNamingResult(BaseModel):
    """Outcome of a naming run (validated)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(default="", max_length=255)
    search_keywords: str = Field(
        default="",
        max_length=4096,
        description="Пул для ручного поиска в Odoo (кроссы, синонимы, сырой текст).",
    )
    description: str = ""
    status: Literal["generated", "review", "error"]
    source_hash: str = ""
    warnings: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    template_pattern_used: str | None = None
    truncated: bool = False

    @model_validator(mode="after")
    def _validate_source_hash_format(self) -> GeneratedNamingResult:
        if self.source_hash and len(self.source_hash) != 64:
            raise ValueError("source_hash must be 64-char hex or empty")
        return self


class NamingExportManifest(BaseModel):
    """Paths written by :func:`export_naming_result`."""

    json_path: str
    txt_path: str


class BatchNamingErrorItem(BaseModel):
    """Per-product failure in a batch naming run."""

    product_id: int
    reason: str


class BatchGenerateNameRequest(BaseModel):
    """Body for ``POST /api/products/batch/generate-name``."""

    product_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Duplicate ids are processed once (first occurrence order preserved).",
    )


class BatchGenerateNameResponse(BaseModel):
    """Summary for batch naming (fault-tolerant per row)."""

    ok_count: int = Field(
        description="Rows where generation finished with status generated/review (no logical error).",
    )
    persisted_count: int = Field(
        description="Rows where the database was updated by persist_generation_result.",
    )
    skipped_locked_count: int = Field(
        description="Rows skipped because name_locked is set.",
    )
    skipped_idempotent_count: int = Field(
        description="Rows where outcome matched stored hash/name — no DB write.",
    )
    errors: list[BatchNamingErrorItem] = Field(default_factory=list)
