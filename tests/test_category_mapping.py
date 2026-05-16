"""Tests for part_type_trigger templates and part_type_folder_map seeding."""

from __future__ import annotations

import pytest

import src.db as db_module
from scripts.seed_category_mapping import FOLDER_MAPPING, PART_TYPE_TEMPLATES, seed_category_mapping
from src.db import get_conn, init_db
from src.template_engine import load_active_template


@pytest.fixture
def db(tmp_path: object, monkeypatch: pytest.MonkeyPatch):
    db_path = str(tmp_path / "catmap2.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    init_db()
    yield db_module


def test_load_active_template_part_type_trigger_overrides_base(db: object) -> None:
    with get_conn() as conn:
        seed_category_mapping(conn)

    p = load_active_template(
        "fitment_base",
        "fitment",
        "Колодки тормозные Передние",
    )
    assert p is not None
    assert "{part_type}" in p
    assert "для" not in p

    p2 = load_active_template(
        "fitment_base",
        "fitment",
        None,
    )
    assert p2 is not None
    assert p != p2


def test_load_active_template_universal_trigger(db: object) -> None:
    with get_conn() as conn:
        seed_category_mapping(conn)
    p = load_active_template(
        "universal_base",
        "universal",
        "Ароматизатор подвесной",
    )
    assert p is not None
    assert "{characteristics}" in p


def test_seed_category_mapping_idempotent(db: object) -> None:
    with get_conn() as conn:
        a1, f1 = seed_category_mapping(conn)
        n1 = conn.execute(
            "SELECT COUNT(*) FROM templates WHERE part_type_trigger IS NOT NULL"
        ).fetchone()[0]
        a2, f2 = seed_category_mapping(conn)
        n2 = conn.execute(
            "SELECT COUNT(*) FROM templates WHERE part_type_trigger IS NOT NULL"
        ).fetchone()[0]
    assert n1 == n2 == len(PART_TYPE_TEMPLATES)
    assert a2 == 0
    assert f2 == 0
    assert a1 > 0
    assert f1 > 0


def test_folder_mapping_covers_top20_audit_part_types(db: object) -> None:
    """First 20 keys in FOLDER_MAPPING match seeded part_type_folder_map rows."""
    top20 = list(FOLDER_MAPPING.keys())[:20]
    with get_conn() as conn:
        seed_category_mapping(conn)
        for pt in top20:
            row = conn.execute(
                "SELECT ms_folder_path FROM part_type_folder_map WHERE part_type = ?",
                (pt,),
            ).fetchone()
            assert row is not None
            assert row[0] == FOLDER_MAPPING[pt]
