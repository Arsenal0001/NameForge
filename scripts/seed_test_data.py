"""
Load fixed test products into the default SQLite database.

Run from project root: python scripts/seed_test_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.db import get_conn, init_db  # noqa: E402
from src.fitment_repo import FitmentRow, save_fitment  # noqa: E402

_TEMPLATE_VERSION = "v1"

TEST_MS_IDS = (
    "test-uuid-001",
    "test-uuid-002",
    "test-uuid-003",
)


def _remove_existing() -> None:
    placeholders = ", ".join("?" * len(TEST_MS_IDS))
    with get_conn() as conn:
        conn.execute(
            f"DELETE FROM products WHERE ms_product_id IN ({placeholders})",
            TEST_MS_IDS,
        )


def _insert_product(
    conn,
    *,
    ms_product_id: str,
    external_code: str,
    article: str,
    brand: str,
    part_type: str,
    applicability_type: str,
    template_key: str,
    generation_status: str,
    name_locked: int = 0,
    source_hash: str = "",
    side_axis: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO products (
            ms_product_id, external_code, article, brand, part_type,
            applicability_type, side_axis, template_key, template_version,
            generation_status, name_locked, source_hash
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ms_product_id,
            external_code,
            article,
            brand,
            part_type,
            applicability_type,
            side_axis,
            template_key,
            _TEMPLATE_VERSION,
            generation_status,
            name_locked,
            source_hash,
        ),
    )
    return int(cur.lastrowid)


def main() -> None:
    init_db()
    _remove_existing()

    with get_conn() as conn:
        pid1 = _insert_product(
            conn,
            ms_product_id="test-uuid-001",
            external_code="TEST001",
            article="P85075",
            brand="Brembo",
            part_type="Колодки тормозные",
            applicability_type="fitment",
            template_key="fitment_base",
            generation_status="new",
            name_locked=0,
            source_hash="",
        )
        pid2 = _insert_product(
            conn,
            ms_product_id="test-uuid-002",
            external_code="TEST002",
            article="W712/94",
            brand="MANN-FILTER",
            part_type="Фильтр масляный",
            applicability_type="universal",
            template_key="universal_base",
            generation_status="new",
        )
        pid3 = _insert_product(
            conn,
            ms_product_id="test-uuid-003",
            external_code="TEST003",
            article="23849",
            brand="Febi",
            part_type="Амортизатор",
            applicability_type="fitment",
            side_axis="Задний левый",
            template_key="fitment_base",
            generation_status="new",
        )

    save_fitment(
        pid1,
        [
            FitmentRow(
                product_id=pid1,
                make="BMW",
                model="3 Series",
                body="E90",
                year_from=2005,
                year_to=2012,
                engine="2.0d",
                sort_order=0,
            ),
            FitmentRow(
                product_id=pid1,
                make="BMW",
                model="1 Series",
                body="E87",
                year_from=2004,
                year_to=2011,
                engine="2.0d",
                sort_order=1,
            ),
        ],
    )
    save_fitment(
        pid3,
        [
            FitmentRow(
                product_id=pid3,
                make="BMW",
                model="X5",
                body="E70",
                year_from=2006,
                year_to=0,
                engine="3.0d",
                sort_order=0,
            ),
        ],
    )

    print(
        f"Seeded 3 test products: ids {pid1} (fitment), {pid2} (universal), {pid3} (fitment, year_to=0)."
    )


if __name__ == "__main__":
    main()
