"""
Seed ``templates`` with per-category (``part_type_pattern``) patterns for the
top-10 categories.

Run from project root:
    python scripts/seed_part_type_templates.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.db import get_conn, init_db  # noqa: E402

# (template_key, version, applicability_type, part_type_pattern, name_pattern)
# template_key is the "namespace" for dedupe; part_type_pattern is what the
# lookup actually matches in load_active_template().
SEED_ROWS: list[tuple[str, str, str, str, str]] = [
    (
        "brakes_pads_fitment",
        "v1",
        "fitment",
        "Колод*",
        "{brand} Колодки {side} {make} {model} {body} {year_from}-{year_to} {article}",
    ),
    (
        "brakes_disk_fitment",
        "v1",
        "fitment",
        "Диск тормозной*",
        "{brand} Тормозной диск {side} {make} {model} {body} {year_from}-{year_to} {article}",
    ),
    (
        "filter_oil_universal",
        "v1",
        "universal",
        "Фильтр масл*",
        "{brand} Фильтр масляный {article} {make} {model} {engine}",
    ),
    (
        "filter_air_universal",
        "v1",
        "universal",
        "Фильтр воздуш*",
        "{brand} Фильтр воздушный {article} {make} {model} {engine}",
    ),
    (
        "filter_fuel_universal",
        "v1",
        "universal",
        "Фильтр топливн*",
        "{brand} Фильтр топливный {article} {make} {model} {engine}",
    ),
    (
        "filter_cabin_universal",
        "v1",
        "universal",
        "Фильтр салон*",
        "{brand} Фильтр салонный {article} {make} {model}",
    ),
    (
        "shock_absorber_fitment",
        "v1",
        "fitment",
        "Амортизатор*",
        "{brand} Амортизатор {side} {make} {model} {body} {year_from}-{year_to} {article}",
    ),
    (
        "stabilizer_link_fitment",
        "v1",
        "fitment",
        "Стойка стабилизатора*",
        "{brand} Стойка стабилизатора {side} {make} {model} {body} {year_from}-{year_to} {article}",
    ),
    (
        "spark_plug_universal",
        "v1",
        "universal",
        "Свеча зажигания*",
        "{brand} Свеча зажигания {article} {make} {model} {engine}",
    ),
    (
        "timing_belt_universal",
        "v1",
        "universal",
        "Ремень ГРМ*",
        "{brand} Ремень ГРМ {article} {make} {model} {engine}",
    ),
    # Baseline defaults kept as catch-all fallback (wildcard on part_type).
    (
        "universal_base",
        "v1",
        "universal",
        "*",
        "{brand} {part_type} {article} {side}",
    ),
    (
        "fitment_base",
        "v1",
        "fitment",
        "*",
        "{brand} {part_type} {article} для {make} {model} {body} {years} {engine} {side}",
    ),
]

_UPSERT_SQL = """
    INSERT INTO templates (
        template_key, version, applicability_type, name_pattern,
        part_type_pattern, is_active
    )
    VALUES (?, ?, ?, ?, ?, 1)
    ON CONFLICT(template_key, version) DO UPDATE SET
        applicability_type = excluded.applicability_type,
        name_pattern       = excluded.name_pattern,
        part_type_pattern  = excluded.part_type_pattern,
        is_active          = 1
"""


def main() -> int:
    init_db()
    with get_conn() as conn:
        for template_key, version, appl, pattern_glob, name_pattern in SEED_ROWS:
            conn.execute(
                _UPSERT_SQL,
                (template_key, version, appl, name_pattern, pattern_glob),
            )
        total = conn.execute(
            "SELECT COUNT(*) FROM templates WHERE is_active = 1"
        ).fetchone()[0]
    print(
        f"templates seeded: {len(SEED_ROWS)} rows upserted; "
        f"active total: {total}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
