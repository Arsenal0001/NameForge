"""Parse fitment hints from supplier_raw_name / MS product name (>token<)."""

from __future__ import annotations

import re

_RE_FITMENT_TOKEN = re.compile(r">([^<]+)<")

VAZ_MODELS: frozenset[str] = frozenset(
    {
        "2101",
        "2102",
        "2103",
        "2104",
        "2105",
        "2106",
        "2107",
        "2108",
        "2109",
        "2110",
        "2111",
        "2112",
        "2113",
        "2114",
        "2115",
        "Kalina",
        "Priora",
        "Granta",
        "Vesta",
        "XRAY",
        "Niva",
        "4x4",
    }
)


def parse_fitment_token(supplier_raw_name: str) -> str | None:
    """
    Extract first ``>...<`` token from text.
    Examples: ``>2107<`` → ``2107``; ``>Golf VII<`` → ``Golf VII``; none → ``None``.
    """
    if not supplier_raw_name:
        return None
    m = _RE_FITMENT_TOKEN.search(supplier_raw_name)
    if not m:
        return None
    inner = m.group(1).strip()
    return inner or None


def resolve_make_from_model(model_token: str) -> tuple[str, str] | None:
    """
    Map known model token to (make, model). Returns None if unknown (operator / aliases).
    """
    if not model_token or not str(model_token).strip():
        return None
    token = str(model_token).strip()
    if token in VAZ_MODELS:
        return ("ВАЗ", token)
    return None
