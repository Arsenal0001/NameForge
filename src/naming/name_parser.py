"""Regex parser: raw MoySklad-style name -> PartName."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .name_model import PartName

_CATEGORY_RE = re.compile(r"\{\{(.+?)\}\}")
_FITMENT_RE = re.compile(r">([^<]+)<")
_SPEC_RE = re.compile(r"\[([^\[\]]+)\]")
_COLOR_RE = re.compile(r"\(\((.+?)\)\)")
_BRAND_RE = re.compile(r"\[\[(.+?)\]\]")
_SERIAL_RE = re.compile(r"#(\d+)")
_PREFIX_RE = re.compile(r"^(Уценка|!)\s+")


def parse(raw: str) -> PartName | None:
    from .name_model import PartName

    s = (raw or "").strip()
    if not s:
        return None

    cat_m = _CATEGORY_RE.search(s)
    if not cat_m:
        return None

    category = (cat_m.group(1) or "").strip()

    prefix: str | None = None
    pre_m = _PREFIX_RE.match(s)
    if pre_m:
        prefix = pre_m.group(1)

    brand_m = _BRAND_RE.search(s)
    brand = (brand_m.group(1).strip() if brand_m else "") or "NON"

    spec_work = _BRAND_RE.sub("", s)
    specs = [(m.group(1) or "").strip() for m in _SPEC_RE.finditer(spec_work)]
    specs = [x for x in specs if x]

    colors = [(m.group(1) or "").strip() for m in _COLOR_RE.finditer(s)]
    colors = [x for x in colors if x]

    fitments = [(m.group(1) or "").strip() for m in _FITMENT_RE.finditer(s)]
    fitments = [x for x in fitments if x]
    fitment: list[str] | None = fitments if fitments else None

    serial_m = _SERIAL_RE.search(s)
    serial = int(serial_m.group(1)) if serial_m else None

    return PartName(
        prefix=prefix,
        category=category,
        fitment=fitment,
        specs=specs,
        colors=colors,
        brand=brand,
        serial=serial,
    )
