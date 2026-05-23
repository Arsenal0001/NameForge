"""Ensure anti-tautology keeps measurement tokens in generated names."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.text_utils import remove_words_subsumed_in_part_type  # noqa: E402


def test_measurement_tokens_not_stripped_by_tautology() -> None:
    name = "Стартер 1.2 кВт 11 зубьев VALEO"
    part_type = "Стартер"
    cleaned = remove_words_subsumed_in_part_type(name, part_type)
    assert cleaned.startswith("Стартер")
    assert "1.2" in cleaned or "кВт" in cleaned
    assert "11" in cleaned
    assert "зубьев" in cleaned


def test_multword_part_type_prefix_preserved() -> None:
    name = "Консервант антикоррозийный 1 л Пушсало ELTRANS"
    part_type = "Консервант антикоррозийный"
    cleaned = remove_words_subsumed_in_part_type(name, part_type)
    assert cleaned.startswith("Консервант антикоррозийный")
    assert "1 л" in cleaned
    assert "ELTRANS" in cleaned
