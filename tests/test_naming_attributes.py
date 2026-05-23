"""Naming integration tests for JSONL attribute_summary injection."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.schemas.naming import ProductNamingInput  # noqa: E402
from app.services.template_service import generate_naming_result  # noqa: E402


def test_attributes_summary_injected_into_characteristics_token() -> None:
    result = generate_naming_result(
        pattern="{part_type} {characteristics} {brand}",
        inp=ProductNamingInput(
            part_type="Антифриз",
            brand="MASTERWAX",
            article="06575",
            applicability_type="universal",
            attributes_summary="1000 мл Аэрозоль Черный",
        ),
        fitments=[],
        primary=None,
    )

    assert "Аэрозоль" in result.name
    assert "Черный" in result.name
    assert "MASTERWAX" in result.name
    assert "л" in result.name


def test_attributes_token_available_in_custom_pattern() -> None:
    result = generate_naming_result(
        pattern="{part_type} {attributes} {brand}",
        inp=ProductNamingInput(
            part_type="Колодки тормозные",
            brand="VALEO",
            article="04966",
            applicability_type="universal",
            attributes_summary="11 зубьев",
        ),
        fitments=[],
        primary=None,
    )

    assert "11 зубьев" in result.name
    assert "VALEO" in result.name


def test_does_not_auto_inject_attributes_when_pattern_omits_token() -> None:
    result = generate_naming_result(
        pattern="{part_type} {brand}",
        inp=ProductNamingInput(
            part_type="Антигравий",
            brand="MASTERWAX",
            article="06575",
            applicability_type="universal",
            attributes_summary="1000 мл Аэрозоль Черный",
        ),
        fitments=[],
        primary=None,
    )

    assert result.name == "Антигравий MASTERWAX"
    assert "Аэрозоль" not in result.name
    assert "Черный" not in result.name
