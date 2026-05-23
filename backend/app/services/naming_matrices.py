"""Logical naming matrices (aligned with ``NAMING_TEMPLATES.md``) and DB template keys."""

from __future__ import annotations

from typing import Literal

# Logical ids stored on ``OdooCategory.naming_template_key`` (UI / API).
NAMING_MATRIX_DEFINITIONS: tuple[tuple[str, str, str], ...] = (
    ("car_mats", "Автомобильные коврики", "[Тип] [Место] [Применяемость] [Материал] [Цвет] …"),
    ("seat_covers", "Чехлы и накидки на сиденья", "[Тип] [Применяемость] [Позиция] [Материал] …"),
    ("bulbs_led", "Автолампы и светодиоды", "[Тип] [Источник света] [Цоколь] [Температура] …"),
    ("multimedia", "Магнитолы и мультимедиа", "[Тип] [ОС] [Диагональ] [ОЗУ]/[ПЗУ] …"),
    ("suspension", "Подвеска и рулевая", "[Тип] [Ось] [Сторона] [Применяемость] …"),
    ("brakes", "Тормозные колодки и диски", "[Тип] [Ось] [Применяемость] …"),
    ("radiators", "Радиаторы", "[Тип] [Применяемость] [КПП] [Кондиционер] …"),
    ("oils", "Технические жидкости (масла)", "[Тип] [Тип масла] [Вязкость] [Объём] …"),
    ("batteries", "Аккумуляторы", "[Тип] [Ёмкость] [Пусковой ток] [Полярность] …"),
    ("wipers", "Щётки стеклоочистителя", "[Тип] [Конструкция] [Длина] …"),
    ("optics", "Оптика в сборе", "[Тип] [Сторона] [Применяемость] …"),
    ("auto_chemistry", "Автохимия и косметика", "[Тип] [Форм-фактор] [Цвет] [Объём] …"),
    ("universal", "Универсальный (fallback)", "[Тип] [Применяемость] [Атрибуты] [Бренд]"),
)

LOGICAL_MATRIX_IDS: frozenset[str] = frozenset(m[0] for m in NAMING_MATRIX_DEFINITIONS)

# Seed patterns: SKU stays out of Product Name (NAMING_TEMPLATES_V2 §1 synergy).
_PATTERN_FITMENT = "{part_type} {installation} {fitment_core} {attributes} {brand}"
_PATTERN_UNIVERSAL = "{part_type} {installation} {attributes} {brand}"


def physical_template_key(matrix_id: str, applicability: Literal["fitment", "universal"]) -> str:
    """Row in ``templates.template_key`` — one row per (logical matrix × applicability)."""
    return f"{matrix_id}__{applicability}"


def is_valid_matrix_id(value: str | None) -> bool:
    return bool(value and value.strip() in LOGICAL_MATRIX_IDS)
