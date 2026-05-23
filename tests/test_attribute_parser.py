"""Tests for JSONL attribute → Russian name fragment conversion."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.attribute_parser import format_attributes_to_russian  # noqa: E402
from app.services.text_utils import STUB_VALUES  # noqa: E402


def test_format_attributes_volume_color_form_factor() -> None:
    result = format_attributes_to_russian(
        {
            "color": "Черный",
            "volume_ml": 1000,
            "form_factor": "Аэрозоль",
        }
    )
    assert result == "1000 мл Аэрозоль Черный"


def test_format_attributes_priority_volume_before_color() -> None:
    result = format_attributes_to_russian(
        {
            "color": "Черный",
            "volume_ml": 500,
        }
    )
    assert result.index("500") < result.index("Черный")


def test_format_attributes_power_and_teeth() -> None:
    result = format_attributes_to_russian(
        {
            "power_kw": 1.2,
            "teeth_count": 11,
        }
    )
    assert result == "1.2 кВт 11 зубьев"


def test_format_attributes_unknown_key_fallback() -> None:
    result = format_attributes_to_russian({"material": "Резина"})
    assert result == "Резина"


def test_format_attributes_skips_side_axis_keys() -> None:
    result = format_attributes_to_russian(
        {
            "side": "передний",
            "color": "Красный",
        }
    )
    assert result == "Красный"


@pytest.mark.parametrize("stub", ["?", "NON", "н/а"])
def test_format_attributes_respects_stub_values(stub: str) -> None:
    assert stub.casefold() in STUB_VALUES or stub.lower() in STUB_VALUES
    result = format_attributes_to_russian({"color": stub, "volume_ml": 500})
    assert result == "500 мл"
