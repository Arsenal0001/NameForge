"""Tests for ERP stub token sanitization and generated-name polishing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.schemas.naming import ProductNamingInput  # noqa: E402
from app.services.template_service import (  # noqa: E402
    _polish_generated_name,
    generate_naming_result,
    skip_brand,
)
from app.services.text_utils import STUB_VALUES, sanitize_token_value  # noqa: E402


@pytest.mark.parametrize(
    "raw",
    ["?", "NON", "н/а", "N/A", "без бренда", "No Name", "-", "отсутствует"],
)
def test_sanitize_token_value_drops_stub_values(raw: str) -> None:
    assert sanitize_token_value(raw) == ""


def test_sanitize_token_value_keeps_real_brand() -> None:
    assert sanitize_token_value("MANN") == "MANN"
    assert sanitize_token_value("  Bosch  ") == "Bosch"


def test_skip_brand_uses_stub_values_without_breaking_non() -> None:
    assert skip_brand("NON") is True
    assert skip_brand("Mann") is False


def test_stub_brand_question_mark_yields_clean_name_without_double_spaces() -> None:
    result = generate_naming_result(
        pattern="{part_type}  {installation}  {brand}",
        inp=ProductNamingInput(
            part_type="Фильтр масляный",
            brand="?",
            article="W712/75",
            applicability_type="universal",
            installation_location="передний",
        ),
        fitments=[],
        primary=None,
    )

    assert "?" not in result.name
    assert "  " not in result.name
    assert "передний" in result.name
    assert result.name.strip() == result.name
    assert "brand_skipped" in result.warnings


def test_polish_generated_name_collapses_whitespace_and_punctuation() -> None:
    polished = _polish_generated_name("Фильтр   масляный  ,  MANN")
    assert polished == "Фильтр масляный, MANN"


def test_stub_values_include_legacy_unknown() -> None:
    assert "unknown" in STUB_VALUES
