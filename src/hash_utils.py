"""Stable hashing for source_hash / candidate_hash (generation gating)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _scalar(v: Any) -> str:
    """None → empty string; otherwise str() so 0 stays '0'."""
    if v is None:
        return ""
    return str(v)


def _encode_fitment_row(row: dict) -> str:
    """Pipe-separated segment; year_to = 0 included as \"0\"."""
    return "|".join(
        (
            _scalar(row.get("make")),
            _scalar(row.get("model")),
            _scalar(row.get("body")),
            _scalar(row.get("year_from")),
            _scalar(row.get("year_to")),
            _scalar(row.get("engine")),
        )
    )


def _fitment_sort_key(row: dict) -> tuple[str, str, str, str]:
    return (
        _scalar(row.get("make")),
        _scalar(row.get("model")),
        _scalar(row.get("body")),
        _scalar(row.get("year_from")),
    )


def compute_source_hash(product: dict, fitment_rows: list[dict]) -> str:
    """
    Canonical SHA-256 hex digest over JSON (sort_keys=True, ensure_ascii=False).

    Universal: brand, part_type, article, side_axis, cross_numbers,
    template_key, template_version, applicability_type.

    Fitment: those fields plus primary_make, primary_model, primary_body,
    year_from, year_to, engine and all fitment rows (sorted, pipe-encoded).
    """
    universal_keys = (
        "brand",
        "part_type",
        "article",
        "side_axis",
        "cross_numbers",
        "template_key",
        "template_version",
        "applicability_type",
    )
    primary_keys = (
        "primary_make",
        "primary_model",
        "primary_body",
        "year_from",
        "year_to",
        "engine",
    )

    payload: dict[str, Any] = {k: _scalar(product.get(k)) for k in universal_keys}

    applicability = payload["applicability_type"]
    if applicability == "fitment":
        for k in primary_keys:
            payload[k] = _scalar(product.get(k))
        rows = list(fitment_rows)
        rows.sort(key=_fitment_sort_key)
        payload["fitment_segments"] = [_encode_fitment_row(r) for r in rows]

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
