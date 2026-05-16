"""Tests for src.category_mapper — exact + fnmatch resolution on category_mapping."""

from __future__ import annotations

import pytest

from src.category_mapper import resolve_folder
from src.db import get_conn


@pytest.fixture
def db(tmp_path: object, monkeypatch: pytest.MonkeyPatch):
    """Isolated SQLite per test, seeded with a small mapping set."""
    import src.db as db_module

    db_path = str(tmp_path / "catmap.db")
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    db_module.init_db()

    rules = [
        ("Колодки тормозные", "Тормозная система/Колодки", 100),
        ("Колодки*", "Тормозная система/Колодки", 50),
        ("Фильтр масляный", "Двигатель/Фильтры", 100),
        ("Фильтр*", "Двигатель/Фильтры", 50),
        ("Амортизатор*", "Подвеска/Амортизаторы", 50),
    ]
    with get_conn() as conn:
        for pattern, folder, priority in rules:
            conn.execute(
                """
                INSERT INTO category_mapping
                    (part_type_pattern, ms_folder_path, priority, is_active)
                VALUES (?, ?, ?, 1)
                """,
                (pattern, folder, priority),
            )
    return db_module


def test_exact_match_kolodki(db: object) -> None:
    assert resolve_folder("Колодки тормозные") == "Тормозная система/Колодки"


def test_casefold_exact_match_upper(db: object) -> None:
    assert resolve_folder("КОЛОДКИ ТОРМОЗНЫЕ") == "Тормозная система/Колодки"


def test_exact_match_filter_oil(db: object) -> None:
    assert resolve_folder("Фильтр масляный") == "Двигатель/Фильтры"


def test_unknown_part_type_returns_none(db: object) -> None:
    assert resolve_folder("Совершенно неизвестный тип") is None


def test_glob_pattern_amortizator_zadniy(db: object) -> None:
    assert resolve_folder("Амортизатор задний") == "Подвеска/Амортизаторы"


def test_empty_input_returns_none(db: object) -> None:
    assert resolve_folder("") is None
    assert resolve_folder("   ") is None


def test_inactive_rule_ignored(db: object) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO category_mapping
                (part_type_pattern, ms_folder_path, priority, is_active)
            VALUES ('Ржавый болт', 'Крепёж/Болты', 100, 0)
            """
        )
    assert resolve_folder("Ржавый болт") is None
