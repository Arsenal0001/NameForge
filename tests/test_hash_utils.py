"""Tests for src.hash_utils — deterministic hashing, no I/O."""

from __future__ import annotations

import copy

from src.hash_utils import compute_source_hash


def _base_product(**overrides: object) -> dict:
    p = {
        "brand": "Bosch",
        "part_type": "Фильтр",
        "article": "W712",
        "side_axis": "",
        "cross_numbers": "",
        "template_key": "fitment_base",
        "template_version": "v1",
        "applicability_type": "fitment",
        "primary_make": "VW",
        "primary_model": "Golf",
        "primary_body": "Mk7",
        "year_from": 2015,
        "year_to": 2020,
        "engine": "1.6",
    }
    p.update(overrides)
    return p


def test_same_input_same_hash() -> None:
    prod = _base_product()
    rows = [
        {"make": "BMW", "model": "3", "year_from": 2005, "year_to": 2010},
    ]
    a = compute_source_hash(prod, rows)
    b = compute_source_hash(copy.deepcopy(prod), copy.deepcopy(rows))
    assert a == b
    assert len(a) == 64


def test_change_brand_changes_hash() -> None:
    prod = _base_product()
    rows: list[dict] = []
    h1 = compute_source_hash(prod, rows)
    prod2 = copy.deepcopy(prod)
    prod2["brand"] = "Mann"
    h2 = compute_source_hash(prod2, rows)
    assert h1 != h2


def test_change_fitment_row_changes_hash() -> None:
    prod = _base_product()
    r1 = [{"make": "Audi", "model": "A4", "body": "", "year_from": 2010, "year_to": 2015, "engine": ""}]
    r2 = [{"make": "Audi", "model": "A6", "body": "", "year_from": 2010, "year_to": 2015, "engine": ""}]
    assert compute_source_hash(prod, r1) != compute_source_hash(prod, r2)


def test_fitment_row_order_irrelevant() -> None:
    prod = _base_product()
    row_a = {"make": "Audi", "model": "A4", "body": "B8", "year_from": 2008, "year_to": 2015, "engine": "2.0"}
    row_b = {"make": "BMW", "model": "3", "body": "E90", "year_from": 2005, "year_to": 2012, "engine": "2.0d"}
    h1 = compute_source_hash(prod, [row_a, row_b])
    h2 = compute_source_hash(prod, [row_b, row_a])
    assert h1 == h2


def test_year_to_zero_in_fitment_segment_not_empty() -> None:
    prod = _base_product()
    with_zero = [{"make": "X", "model": "Y", "body": "", "year_from": 2018, "year_to": 0, "engine": ""}]
    missing_to = [{"make": "X", "model": "Y", "body": "", "year_from": 2018, "year_to": None, "engine": ""}]
    hz = compute_source_hash(prod, with_zero)
    hm = compute_source_hash(prod, missing_to)
    assert hz != hm


def test_universal_fitment_rows_ignored() -> None:
    prod = _base_product(applicability_type="universal")
    prod.pop("primary_make", None)
    prod.pop("primary_model", None)
    rows_a = [{"make": "ZZZ", "model": "QQQ"}]
    rows_b: list[dict] = []
    assert compute_source_hash(prod, rows_a) == compute_source_hash(prod, rows_b)


def test_none_values_no_exception() -> None:
    prod = {
        "brand": None,
        "part_type": None,
        "article": None,
        "side_axis": None,
        "cross_numbers": None,
        "template_key": "universal_base",
        "template_version": "v1",
        "applicability_type": "universal",
    }
    rows = [{"make": None, "model": None, "body": None, "year_from": None, "year_to": None, "engine": None}]
    h = compute_source_hash(prod, rows)
    assert isinstance(h, str)
    assert len(h) == 64
