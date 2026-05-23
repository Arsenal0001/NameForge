"""Convert JSONL ``attributes`` objects into Russian name fragments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.text_utils import sanitize_token_value

_PRIORITY_GROUPS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        10,
        (
            "voltage_v",
            "power_kw",
            "power_w",
            "amperage_ah",
            "base_type",
            "volume_ml",
            "weight_g",
        ),
    ),
    (
        20,
        (
            "teeth_count",
            "pins_count",
            "splines_count",
            "diameter_mm",
            "length_mm",
            "thread_size",
            "gearbox_type",
            "gearbox_compatibility",
        ),
    ),
    (
        30,
        (
            "technology",
            "composition_type",
            "color_temp_k",
        ),
    ),
    (
        40,
        (
            "form_factor",
            "color",
        ),
    ),
)

PRIORITY_WEIGHTS: dict[str, int] = {}
_TIER_INDEX: dict[str, int] = {}
_tier_cursor = 0
for _weight, _keys in _PRIORITY_GROUPS:
    for _key in _keys:
        PRIORITY_WEIGHTS[_key] = _weight
        _TIER_INDEX[_key] = _tier_cursor
        _tier_cursor += 1

_EXCLUDED_ATTRIBUTE_KEYS: frozenset[str] = frozenset(
    {
        "side",
        "axis",
        "installation_location",
        "сторона",
        "ось",
    }
)


def _attribute_sort_key(key: str) -> tuple[int, int, str]:
    return (
        PRIORITY_WEIGHTS.get(key, 99),
        _TIER_INDEX.get(key, 9999),
        key.casefold(),
    )


def sort_attribute_keys(keys: Mapping[str, Any] | list[str]) -> list[str]:
    """Return JSONL attribute keys sorted by PIM priority weights."""
    if isinstance(keys, Mapping):
        iterable = keys.keys()
    else:
        iterable = keys
    filtered = [
        str(key).strip()
        for key in iterable
        if str(key or "").strip()
        and str(key).strip().casefold() not in _EXCLUDED_ATTRIBUTE_KEYS
    ]
    return sorted(filtered, key=_attribute_sort_key)


def _format_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, list):
        parts = [_format_scalar(item) for item in value]
        return " ".join(part for part in parts if part)
    text = str(value).strip()
    return text


def format_attribute_value(key: str, value: Any) -> str:
    """Format one JSONL attribute value for names and Odoo attribute lines."""
    raw = _format_scalar(value)
    if not raw:
        return ""
    if sanitize_token_value(raw) == "":
        return ""

    if key == "power_kw":
        return f"{raw} кВт"
    if key == "power_w":
        return f"{raw} Вт"
    if key == "voltage_v":
        return f"{raw} В"
    if key == "amperage_ah":
        return f"{raw} Ач"
    if key == "volume_ml":
        return f"{raw} мл"
    if key == "weight_g":
        return f"{raw} г"
    if key == "teeth_count":
        return f"{raw} зубьев"
    if key == "pins_count":
        return f"{raw} контактов"
    if key == "splines_count":
        return f"{raw} шлицов"
    if key == "diameter_mm":
        return f"{raw} мм"
    if key == "length_mm":
        return f"{raw} мм"
    if key == "color_temp_k":
        return f"{raw} K"
    if key in {
        "color",
        "form_factor",
        "composition_type",
        "base_type",
        "technology",
        "thread_size",
        "gearbox_type",
        "gearbox_compatibility",
    }:
        return raw
    return raw


def format_attributes_to_russian(attributes: Mapping[str, Any] | None) -> str:
    """
    Build a spaced Russian characteristics line from a JSONL ``attributes`` dict.

    Keys are sorted by :data:`PRIORITY_WEIGHTS` before formatting.
    """
    if not attributes:
        return ""

    normalized: dict[str, Any] = {}
    for raw_key, raw_value in attributes.items():
        key = str(raw_key or "").strip()
        if not key or key.casefold() in _EXCLUDED_ATTRIBUTE_KEYS:
            continue
        normalized[key] = raw_value

    if not normalized:
        return ""

    chunks: list[str] = []
    seen_values: set[str] = set()

    def append_chunk(text: str) -> None:
        cleaned = sanitize_token_value(text)
        if not cleaned:
            return
        marker = cleaned.casefold()
        if marker in seen_values:
            return
        seen_values.add(marker)
        chunks.append(cleaned)

    for key in sort_attribute_keys(normalized):
        append_chunk(format_attribute_value(key, normalized[key]))

    return " ".join(chunks)
