"""
Enrich ``part_type`` / ``brand`` from ``supplier_raw_name`` using ``name_parser.parse``.

Default is dry-run (no UPDATE). Use ``--apply`` to write changes.

  python scripts/enrich_from_raw_name.py --limit 100
  python scripts/enrich_from_raw_name.py --apply --limit 500
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.db import get_conn  # noqa: E402
from src.name_generator import SKIP_BRANDS  # noqa: E402
from src.naming.name_parser import parse  # noqa: E402


def _part_type_empty(v: Any) -> bool:
    return not (str(v or "").strip())


def _brand_empty(v: Any) -> bool:
    return str(v or "").strip().casefold() in SKIP_BRANDS


def _parsed_brand_usable(brand: str) -> bool:
    b = (brand or "").strip()
    return bool(b) and b.casefold() not in SKIP_BRANDS


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich products from supplier_raw_name via name_parser."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform UPDATE (default: dry-run only).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        metavar="N",
        help="Max rows to process (default: 100).",
    )
    args = parser.parse_args()
    dry_run = not args.apply
    lim = max(0, args.limit)

    stats = {
        "processed": 0,
        "part_type": 0,
        "brand": 0,
        "both": 0,
        "nothing": 0,
    }
    examples: list[str] = []

    with get_conn() as conn:
        cur = conn.execute(
            """
            SELECT id, supplier_raw_name, part_type, brand
            FROM products
            WHERE supplier_raw_name IS NOT NULL
              AND TRIM(supplier_raw_name) != ''
            ORDER BY id
            LIMIT ?
            """,
            (lim,),
        )
        rows = cur.fetchall()

        for row in rows:
            pid = int(row[0])
            raw = str(row[1] or "")
            part_type_db = row[2]
            brand_db = row[3]

            stats["processed"] += 1
            parsed = parse(raw)

            pt_empty = _part_type_empty(part_type_db)
            br_empty = _brand_empty(brand_db)

            would_pt = bool(
                parsed
                and pt_empty
                and (parsed.category or "").strip()
            )
            would_br = bool(
                parsed
                and br_empty
                and _parsed_brand_usable(parsed.brand)
            )

            if would_pt:
                stats["part_type"] += 1
            if would_br:
                stats["brand"] += 1
            if would_pt and would_br:
                stats["both"] += 1
            if not would_pt and not would_br:
                stats["nothing"] += 1

            if dry_run and len(examples) < 5 and (would_pt or would_br):
                bits: list[str] = []
                if would_pt and parsed:
                    bits.append(f"part_type←{parsed.category!r}")
                if would_br and parsed:
                    bits.append(f"brand←{parsed.brand!r}")
                examples.append(f"id={pid} | {'; '.join(bits)} | raw={raw[:120]!r}")

            if not dry_run and parsed and (would_pt or would_br):
                sets: list[str] = []
                vals: list[Any] = []
                if would_pt:
                    sets.append("part_type = ?")
                    vals.append((parsed.category or "").strip())
                if would_br:
                    sets.append("brand = ?")
                    vals.append((parsed.brand or "").strip())
                vals.append(pid)
                conn.execute(
                    f"UPDATE products SET {', '.join(sets)} WHERE id = ?",
                    vals,
                )

    print(f"Режим: {'DRY_RUN (без UPDATE)' if dry_run else 'APPLY'}")
    print(f"Лимит: {lim}")
    print(f"Всего обработано: {stats['processed']}")
    print(f"Получено part_type: {stats['part_type']}")
    print(f"Получено brand: {stats['brand']}")
    print(f"Получено оба: {stats['both']}")
    print(f"Ничего не извлечено: {stats['nothing']}")
    if dry_run and examples:
        print("\nПримеры (до 5 строк, где были бы изменения):")
        for line in examples:
            print(" ", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
