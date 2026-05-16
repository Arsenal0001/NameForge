"""SQLite tests for fitment_repo — isolated DB per test via DB_PATH."""

from __future__ import annotations

import pytest

from src.db import get_conn
from src.fitment_repo import (
    FitmentRow,
    build_fitment_summary,
    delete_all_fitment,
    get_fitment,
    save_fitment,
)


@pytest.fixture
def db(tmp_path: object, monkeypatch: pytest.MonkeyPatch):
    """Point DB at an empty temp file (:memory: not used — separate connections see different DB)."""
    import src.db as db_module

    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()
    return db_module


@pytest.fixture
def product_id(db: object) -> int:
    """Minimal template + product rows for FK."""
    ms_id = "test-ms-product"
    ext = "test-ext-code"
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO templates (
                template_key, version, applicability_type, name_pattern
            )
            VALUES ('tb', 'v1', 'fitment', '{brand}')
            """
        )
        conn.execute(
            """
            INSERT INTO products (
                ms_product_id, external_code, article, brand, part_type,
                applicability_type, template_key, template_version, source_hash
            )
            VALUES (?, ?, 'A', 'B', 'T', 'fitment', 'tb', 'v1', '')
            """,
            (ms_id, ext),
        )
        row = conn.execute(
            "SELECT id FROM products WHERE ms_product_id = ?", (ms_id,)
        ).fetchone()
        assert row is not None
        return int(row[0])


def test_get_fitment_empty_when_no_rows(db: object, product_id: int) -> None:
    rows = get_fitment(product_id)
    assert rows == []


def test_save_fitment_one_row_primary_auto(db: object, product_id: int) -> None:
    save_fitment(
        product_id,
        [
            FitmentRow(product_id=product_id, make="Audi", model="A4", sort_order=0),
        ],
    )
    rows = get_fitment(product_id)
    assert len(rows) == 1
    assert rows[0].is_primary == 1


def test_save_fitment_multiple_first_by_sort_order_primary(db: object, product_id: int) -> None:
    save_fitment(
        product_id,
        [
            FitmentRow(product_id=product_id, make="Z", model="Last", sort_order=10),
            FitmentRow(product_id=product_id, make="A", model="First", sort_order=1),
            FitmentRow(product_id=product_id, make="M", model="Mid", sort_order=5),
        ],
    )
    rows = get_fitment(product_id)
    primaries = [r for r in rows if r.is_primary == 1]
    assert len(primaries) == 1
    assert primaries[0].make == "A"
    assert primaries[0].sort_order == 1


def test_save_fitment_selected_primary_id_pins_row(db: object, product_id: int) -> None:
    pin_id = 42  # stale UI id matched before INSERT
    save_fitment(
        product_id,
        [
            FitmentRow(
                product_id=product_id,
                make="First",
                model="Car",
                sort_order=0,
                id=1,
            ),
            FitmentRow(
                product_id=product_id,
                make="Second",
                model="Car",
                sort_order=1,
                id=pin_id,
            ),
        ],
        selected_primary_id=pin_id,
    )
    rows = get_fitment(product_id)
    prim = next(r for r in rows if r.is_primary == 1)
    assert prim.make == "Second"


def test_save_fitment_syncs_primary_make_model(db: object, product_id: int) -> None:
    save_fitment(
        product_id,
        [
            FitmentRow(product_id=product_id, make="Toyota", model="Camry", sort_order=0),
        ],
    )
    with get_conn() as conn:
        row = conn.execute(
            "SELECT primary_make, primary_model FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == "Toyota"
    assert row[1] == "Camry"


def test_save_fitment_exactly_one_primary(db: object, product_id: int) -> None:
    save_fitment(
        product_id,
        [
            FitmentRow(product_id=product_id, make="A", model="1", sort_order=0),
            FitmentRow(product_id=product_id, make="B", model="2", sort_order=1),
        ],
    )
    rows = get_fitment(product_id)
    assert sum(r.is_primary for r in rows) == 1


def test_delete_all_fitment_clears_rows_and_products(db: object, product_id: int) -> None:
    save_fitment(
        product_id,
        [
            FitmentRow(product_id=product_id, make="X", model="Y", sort_order=0),
        ],
    )
    delete_all_fitment(product_id)
    assert get_fitment(product_id) == []
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT primary_make, primary_model, primary_body,
                   year_from, year_to, engine, fitment_summary
            FROM products WHERE id = ?
            """,
            (product_id,),
        ).fetchone()
    assert row is not None
    assert all(v is None for v in row)


def test_build_fitment_summary_year_to_zero_contains_nv() -> None:
    r = FitmentRow(
        product_id=1,
        make="VW",
        model="Golf",
        year_from=2018,
        year_to=0,
    )
    s = build_fitment_summary([r])
    assert "н.в." in s


def test_build_fitment_summary_multiple_semicolon() -> None:
    rows = [
        FitmentRow(product_id=1, make="A", model="1", sort_order=0),
        FitmentRow(product_id=1, make="B", model="2", sort_order=1),
    ]
    s = build_fitment_summary(rows)
    assert s == "A 1; B 2"


def test_save_fitment_second_call_replaces_rows(db: object, product_id: int) -> None:
    save_fitment(
        product_id,
        [
            FitmentRow(product_id=product_id, make="Old1", model="X", sort_order=0),
            FitmentRow(product_id=product_id, make="Old2", model="Y", sort_order=1),
            FitmentRow(product_id=product_id, make="Old3", model="Z", sort_order=2),
        ],
    )
    save_fitment(
        product_id,
        [
            FitmentRow(product_id=product_id, make="New", model="Only", sort_order=0),
        ],
    )
    rows = get_fitment(product_id)
    assert len(rows) == 1
    assert rows[0].make == "New"
