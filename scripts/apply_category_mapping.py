"""
Apply part_type -> folder_path rows to category_mapping and refresh product_folder
for all products in generation_status = 'review'.

Run: python scripts/apply_category_mapping.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.db import get_effective_db_path, run_migrations  # noqa: E402

MAPPING: list[tuple[str, str]] = [
    ("Чехлы сидений", "Аксессуары/Чехлы"),
    ("Чехлы сидений 1-2 ряд", "Аксессуары/Чехлы"),
    ("Линза светодиодная BI-LED", "Освещение"),
    ("Фара противотуманная", "Освещение"),
    ("Фонарь Задний", "Освещение"),
    ("Рамка-адаптер магнитолы Андроид", "Электроника/Автозвук"),
    ("Магнитола Андроид, монитор", "Электроника/Автозвук"),
    ("Глушитель Задний / Основной", "Выхлопная система"),
    ("Амортизатор Передний", "Подвеска/Амортизаторы"),
    ("Товар", "!_ПЕРЕПРОВЕРКА_ПАРСИНГА"),
]

UPSERT_SQL = """
    INSERT INTO category_mapping (part_type, folder_path)
    VALUES (?, ?)
    ON CONFLICT(part_type) DO UPDATE SET folder_path = excluded.folder_path
"""


def main() -> int:
    db = get_effective_db_path()
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)

    for part_type, path in MAPPING:
        conn.execute(UPSERT_SQL, (part_type, path))

    # Preserve legacy filter mapping if it existed
    conn.execute(
        """
        INSERT INTO category_mapping (part_type, folder_path)
        VALUES ('Фильтр', 'Расходники / Фильтры')
        ON CONFLICT(part_type) DO UPDATE SET folder_path = excluded.folder_path
        """
    )

    conn.execute(
        """
        UPDATE products
        SET product_folder = COALESCE(
            (SELECT m.folder_path FROM category_mapping m WHERE m.part_type = products.part_type),
            '!_НЕРАЗОБРАННОЕ'
        )
        WHERE generation_status = 'review'
        """
    )
    conn.commit()

    cur = conn.execute(
        """
        SELECT
            COUNT(*) AS review_total,
            SUM(CASE
                WHEN TRIM(COALESCE(product_folder, '')) != ''
                     AND product_folder != '!_НЕРАЗОБРАННОЕ' THEN 1
                ELSE 0
            END) AS not_unsorted
        FROM products
        WHERE generation_status = 'review'
        """
    )
    row = cur.fetchone()
    review_total = int(row[0] or 0)
    not_unsorted = int(row[1] or 0)

    print("category_mapping: upserted", len(MAPPING), "rows (+ Фильтр)")
    print("product_folder refreshed for status=review")
    print(f"review products total: {review_total}")
    print(f"with folder path other than !_НЕРАЗОБРАННОЕ: {not_unsorted}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
