"""
One-off: move products from generation_status 'new' to 'review' with previews.

1) Rows that cannot generate (missing article, part_type, or fitment make/model)
   are set to ``error`` with a clear Russian ``error_message`` (does not hang).
2) Eligible rows are processed via ``batch_generate_previews`` (chunks of 5).

Persists ``generated_name``; does **not** overwrite ``source_hash`` here.

Run from project root:
  python scripts/unblock_new_to_review.py
  python scripts/unblock_new_to_review.py --limit 50
  python scripts/unblock_new_to_review.py --limit 16000
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

# project root on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.db import get_conn  # noqa: E402
from src.product_workflow import batch_generate_previews  # noqa: E402

_CHUNK = 5

_MARK_INELIGIBLE_SQL = """
UPDATE products
SET generation_status = 'error',
    generated_name = NULL,
    error_message = CASE
      WHEN TRIM(COALESCE(article, '')) = ''
        THEN 'Не задан артикул — генерация невозможна'
      WHEN TRIM(COALESCE(part_type, '')) = ''
        THEN 'Не задан тип детали (part_type) — генерация невозможна'
      WHEN applicability_type = 'fitment'
           AND TRIM(COALESCE(primary_make, '')) = ''
        THEN 'Тип fitment: не задан primary_make — генерация невозможна'
      WHEN applicability_type = 'fitment'
           AND TRIM(COALESCE(primary_model, '')) = ''
        THEN 'Тип fitment: не задан primary_model — генерация невозможна'
      ELSE 'Не выполнены условия для генерации имени'
    END
WHERE generation_status = 'new'
  AND name_locked = 0
  AND (
    TRIM(COALESCE(article, '')) = ''
    OR TRIM(COALESCE(part_type, '')) = ''
    OR (
      applicability_type = 'fitment'
      AND (
        TRIM(COALESCE(primary_make, '')) = ''
        OR TRIM(COALESCE(primary_model, '')) = ''
      )
    )
  )
"""

_ELIGIBLE_SELECT = """
SELECT id FROM products
WHERE generation_status = 'new'
  AND name_locked = 0
  AND TRIM(COALESCE(article, '')) != ''
  AND TRIM(COALESCE(part_type, '')) != ''
  AND (
        applicability_type = 'universal'
        OR (
            applicability_type = 'fitment'
            AND TRIM(COALESCE(primary_make, '')) != ''
            AND TRIM(COALESCE(primary_model, '')) != ''
        )
      )
ORDER BY id
"""


def mark_ineligible_new_as_error(conn) -> int:
    cur = conn.execute(_MARK_INELIGIBLE_SQL)
    return int(cur.rowcount)


def fetch_eligible_new_ids(conn, limit: int | None) -> list[int]:
    sql = _ELIGIBLE_SELECT.strip()
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        rows = conn.execute(sql, (int(limit),)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()
    return [int(r[0]) for r in rows]


def main() -> int:
    p = argparse.ArgumentParser(description="Promote 'new' products to 'review' with previews.")
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max eligible products to process (omit for all eligible remaining)",
    )
    args = p.parse_args()
    limit = args.limit
    if limit is not None and limit < 0:
        print("--limit must be non-negative.")
        return 2

    with get_conn() as conn:
        n_marked = mark_ineligible_new_as_error(conn)
    print(f"Marked ineligible 'new' rows as error: {n_marked}")

    with get_conn() as conn:
        ids = fetch_eligible_new_ids(conn, limit)

    if not ids:
        print("No eligible products in status 'new' — nothing to generate.")
    else:
        print(f"Eligible to process: {len(ids)} (chunk size {_CHUNK}).")
        for i in range(0, len(ids), _CHUNK):
            batch = [str(x) for x in ids[i : i + _CHUNK]]
            try:
                with get_conn() as conn:
                    batch_generate_previews(batch, conn)
            except Exception:
                print(f"Chunk starting at index {i} failed (ids {batch}):")
                traceback.print_exc()

    ph = ",".join("?" * len(ids)) if ids else ""
    if ids:
        with get_conn() as conn:
            moved = conn.execute(
                f"""
                SELECT COUNT(*) FROM products
                WHERE id IN ({ph}) AND generation_status = 'review'
                """,
                ids,
            ).fetchone()[0]
            failed = conn.execute(
                f"""
                SELECT COUNT(*) FROM products
                WHERE id IN ({ph}) AND generation_status = 'error'
                """,
                ids,
            ).fetchone()[0]
            still_new = conn.execute(
                f"""
                SELECT COUNT(*) FROM products
                WHERE id IN ({ph}) AND generation_status = 'new'
                """,
                ids,
            ).fetchone()[0]
        print(f"Among processed ids: review={moved}, error={failed}, still new={still_new}")

    print("Totals:")
    with get_conn() as conn:
        n_review = conn.execute(
            "SELECT COUNT(*) FROM products WHERE generation_status = 'review'"
        ).fetchone()[0]
        n_new = conn.execute(
            "SELECT COUNT(*) FROM products WHERE generation_status = 'new'"
        ).fetchone()[0]
        n_err = conn.execute(
            "SELECT COUNT(*) FROM products WHERE generation_status = 'error'"
        ).fetchone()[0]
    print(f"  generation_status=review: {n_review}")
    print(f"  generation_status=new: {n_new}")
    print(f"  generation_status=error: {n_err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
