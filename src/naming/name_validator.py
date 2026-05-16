"""Validate raw names; optional CSV injection sanitizer."""

from __future__ import annotations

import re
from dataclasses import dataclass

_CONTROLLED_COLORS = frozenset(
    {
        "Черный",
        "Белый",
        "Хром",
        "Красный",
        "Желтый",
        "Серебристый",
        "Синий",
        "Зеленый",
        "Серый",
    }
)

_CATEGORY_RE = re.compile(r"\{\{(.+?)\}\}")
_BRAND_RE = re.compile(r"\[\[(.+?)\]\]")


@dataclass(frozen=True)
class NameIssue:
    """Single validation problem (plan: code + message)."""

    code: str
    message: str


def sanitize_csv_cell(val: str) -> str:
    """Strip CSV/formula injection prefixes from cell text."""
    s = val.replace("\r", "").replace("\t", " ")
    s = s.lstrip()
    while s and s[0] in "=+-@":
        s = s[1:].lstrip()
    return s


def _balanced_curly(s: str) -> bool:
    return s.count("{{") == s.count("}}")


def _balanced_round(s: str) -> bool:
    return s.count("((") == s.count("))")


def _balanced_square_brand(s: str) -> bool:
    """Heuristic: [[ ... ]] pairs balanced."""
    return s.count("[[") == s.count("]]")


def _spec_tokens_excluding_brand_span(s: str) -> list[str]:
    spec_work = _BRAND_RE.sub("", s)
    return [m.group(1).strip() for m in re.finditer(r"\[([^\[\]]+)\]", spec_work)]


def validate(raw: str) -> list[NameIssue]:
    s = raw or ""
    issues: list[NameIssue] = []

    if len(s) > 120:
        issues.append(NameIssue("LEN", "Длина строки больше 120 символов"))

    if not _CATEGORY_RE.search(s):
        issues.append(NameIssue("NO_CAT", "Нет блока категории {{...}}"))

    if not _BRAND_RE.search(s):
        issues.append(NameIssue("NO_BRAND", "Нет блока бренда [[...]]"))

    if not _balanced_curly(s):
        issues.append(NameIssue("BRACKET", "Несбалансированные {{ }}"))
    if not _balanced_round(s):
        issues.append(NameIssue("BRACKET", "Несбалансированные (( ))"))
    if not _balanced_square_brand(s):
        issues.append(NameIssue("BRACKET", "Несбалансированные [[ ]]"))

    specs = _spec_tokens_excluding_brand_span(s)
    if len(specs) != len(set(specs)):
        issues.append(NameIssue("DUP_SPEC", "Повторяющиеся блоки [spec]"))

    bad_colors: set[str] = set()
    for m in re.finditer(r"\(\((.+?)\)\)", s):
        col = (m.group(1) or "").strip()
        if col and col not in _CONTROLLED_COLORS:
            bad_colors.add(col)
    for col in sorted(bad_colors):
        issues.append(NameIssue("COLOR", f"Цвет «{col}» не из допустимого списка"))

    return issues
