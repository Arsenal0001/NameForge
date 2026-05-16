"""
Fast text helpers for Golden Catalog naming (see ``NAMING_TEMPLATES_V2.md``).

No brand dictionaries, supplier prioritisation, or field priority logic — only
lightweight string passes suitable for ~16k SKU batches.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# Accessories: keep «универсальн*» in copy (mats, covers, wipers, interior add-ons).
_ACCESSORY_PART_HINT = re.compile(
    r"(коврик|багажник|чехол|накидк|щетк|щётк|щетин|рул(ь|я)|ароматизатор|"
    r"держатель|органайзер|шторк|полк\s+багаж)",
    re.IGNORECASE,
)

_UNIVERSAL_WORD = re.compile(
    r"\bуниверсальн(?:ый|ая|ое|ые|ого|ому|ым|их|ую)\b",
    re.IGNORECASE,
)

_RE_ML_GLUED = re.compile(r"(?P<num>\d+(?:[.,]\d+)?)(?P<u>мл|ml)\b", re.IGNORECASE)
_RE_ML_SPACED = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<u>мл|ml)\b", re.IGNORECASE
)
_RE_L_GLUED = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)(?P<u>[lL])(?![a-zA-Za-zа-яА-ЯёЁ])"
)
_RE_L_SPACED = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<u>[lLлЛ])(?![a-zA-Za-zа-яА-ЯёЁ])"
)
_RE_V_GLUED = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)(?P<u>V|v|В|в)(?![a-zA-Za-zа-яА-ЯёЁ])"
)
_RE_V_SPACED = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<u>V|v|В|в)(?![a-zA-Za-zа-яА-ЯёЁ])"
)
_RE_AH_GLUED = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)(?P<u>Ач|ач)(?![а-яА-ЯёЁ])", re.IGNORECASE
)
_RE_AH_SPACED = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<u>Ач|ач|Ah|AH)\b", re.IGNORECASE
)
_RE_MM_GLUED = re.compile(r"(?P<num>\d+(?:[.,]\d+)?)(?P<u>mm|MM|мм)\b")
_RE_MM_SPACED = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<u>mm|MM|мм)\b", re.IGNORECASE
)


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _fmt_num(n: float) -> str:
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    s = f"{n:.6g}"
    return s.rstrip("0").rstrip(".").replace(",", ".")


def _sub_ml(m: re.Match[str]) -> str:
    raw = m.group("num").replace(",", ".")
    try:
        val = float(raw)
    except ValueError:
        return m.group(0)
    if val >= 1000:
        liters = val / 1000.0
        return f"{_fmt_num(liters)} л"
    return f"{_fmt_num(val)} мл"


def _sub_liters(m: re.Match[str]) -> str:
    raw = m.group("num").replace(",", ".")
    try:
        val = float(raw)
    except ValueError:
        return m.group(0)
    return f"{_fmt_num(val)} л"


def _sub_volt(m: re.Match[str]) -> str:
    return f"{m.group('num').replace(',', '.')} В"


def _sub_ah(m: re.Match[str]) -> str:
    return f"{m.group('num').replace(',', '.')} Ач"


def _sub_mm(m: re.Match[str]) -> str:
    return f"{m.group('num').replace(',', '.')} мм"


def normalize_measurement_units(text: str) -> str:
    """Rule 3: spaces before units; common ml/L/V/Ah/mm normalisations."""
    if not text:
        return ""
    x = text
    x = _RE_ML_GLUED.sub(_sub_ml, x)
    x = _RE_ML_SPACED.sub(_sub_ml, x)
    x = _RE_L_GLUED.sub(_sub_liters, x)
    x = _RE_L_SPACED.sub(_sub_liters, x)
    x = _RE_V_GLUED.sub(_sub_volt, x)
    x = _RE_V_SPACED.sub(_sub_volt, x)
    x = _RE_AH_GLUED.sub(_sub_ah, x)
    x = _RE_AH_SPACED.sub(_sub_ah, x)
    x = _RE_MM_GLUED.sub(_sub_mm, x)
    x = _RE_MM_SPACED.sub(_sub_mm, x)
    return x


def preserve_universal_for_accessory_part_type(part_type: str) -> bool:
    """Rule 1 exception — mats/covers/wipers etc."""
    return bool(part_type and _ACCESSORY_PART_HINT.search(part_type))


def strip_universal_qualifiers(text: str, *, preserve: bool) -> str:
    """Rule 1: drop «универсальн*» unless ``preserve`` (accessories)."""
    if preserve or not text:
        return text
    return _UNIVERSAL_WORD.sub("", text)


def _strip_edge_punct(token: str) -> str:
    return token.strip(".,;:!?\"'«»()[]")


def dedupe_consecutive_words(text: str) -> str:
    words = text.split()
    if not words:
        return ""
    out = [words[0]]
    for w in words[1:]:
        if w.casefold() != out[-1].casefold():
            out.append(w)
    return " ".join(out)


def _token_matches_whole_word_in(haystack_cf: str, token_cf: str) -> bool:
    """True if ``token_cf`` occurs in ``haystack_cf`` as a whole word (Unicode \\w boundaries)."""
    if len(token_cf) < 3:
        return False
    return (
        re.search(rf"(?<!\w){re.escape(token_cf)}(?!\w)", haystack_cf, flags=re.IGNORECASE)
        is not None
    )


def remove_words_subsumed_in_part_type(text: str, part_type: str) -> str:
    """
    Drop name tokens that duplicate a whole word already present in ``part_type``.

    Uses strict word boundaries so e.g. «ток» inside «сток» does not match.
    """
    pt = (part_type or "").casefold().strip()
    if len(pt) < 3 or not text:
        return text
    kept: list[str] = []
    for raw_t in text.split():
        t = _strip_edge_punct(raw_t).casefold()
        if len(t) >= 3 and t != pt and _token_matches_whole_word_in(pt, t):
            continue
        kept.append(raw_t)
    return " ".join(kept)


def strip_article_tokens_from_name(name: str, article_primary: str) -> str:
    """Remove SKU tokens matching ``article_primary`` (whole-token)."""
    art = (article_primary or "").strip()
    if not art or not name:
        return name
    art_cf = art.casefold()
    out: list[str] = []
    for tok in name.split():
        if _strip_edge_punct(tok).casefold() == art_cf:
            continue
        out.append(tok)
    return " ".join(out)


def assemble_search_keywords_line(chunks: Sequence[str]) -> str:
    """
    Rule 2 helper: one line for Odoo search custom field — deduped, spaced units.

    Chunks should already reflect operator-visible synonyms / crosses / raw supplier text.
    """
    seen: set[str] = set()
    parts: list[str] = []
    for raw in chunks:
        t = collapse_whitespace(normalize_measurement_units(str(raw)))
        if not t:
            continue
        key = t.casefold()
        if key in seen:
            continue
        seen.add(key)
        parts.append(t)
    return " | ".join(parts)


def apply_golden_name_postprocess(
    raw: str,
    *,
    part_type: str,
    article_primary: str,
) -> str:
    """Ordered passes for Product ``name`` (metrics → universal → tautology → SKU strip)."""
    x = normalize_measurement_units(raw)
    x = strip_universal_qualifiers(
        x,
        preserve=preserve_universal_for_accessory_part_type(part_type),
    )
    x = remove_words_subsumed_in_part_type(x, part_type)
    x = strip_article_tokens_from_name(x, article_primary)
    x = dedupe_consecutive_words(x)
    return collapse_whitespace(x)
