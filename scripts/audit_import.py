"""
Read-only SQLite audit after MoySklad import (Phase D1).

Run from project root:
  python scripts/audit_import.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.db import get_conn  # noqa: E402


def _pct(n: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(100.0 * n / total, 2)


def _nonempty_expr(col: str) -> str:
    return f"SUM(CASE WHEN {col} IS NOT NULL AND TRIM(CAST({col} AS TEXT)) != '' THEN 1 ELSE 0 END)"


def main() -> None:
    lines: list[str] = []
    utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    with get_conn() as conn:
        total = int(conn.execute("SELECT COUNT(*) FROM products").fetchone()[0])

        lines.append("# Import audit (read-only)")
        lines.append("")
        lines.append(f"Generated: {utc}")
        lines.append("")
        lines.append(f"**Total products:** {total}")
        lines.append("")

        if total == 0:
            lines.append("_No rows in `products` — run import first._")
            md = "\n".join(lines)
            print(md)
            out = _ROOT / "docs" / "IMPORT_AUDIT.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(md, encoding="utf-8")
            print(f"\nWritten: {out}")
            return

        # generation_status
        lines.append("## By generation_status")
        lines.append("")
        lines.append("| status | count |")
        lines.append("|--------|------:|")
        for row in conn.execute(
            "SELECT generation_status, COUNT(*) AS c FROM products GROUP BY generation_status ORDER BY c DESC"
        ).fetchall():
            st, c = str(row[0]), int(row[1])
            lines.append(f"| {st} | {c} |")
        lines.append("")

        # applicability_type
        lines.append("## By applicability_type")
        lines.append("")
        lines.append("| type | count |")
        lines.append("|------|------:|")
        for row in conn.execute(
            "SELECT applicability_type, COUNT(*) AS c FROM products GROUP BY applicability_type ORDER BY c DESC"
        ).fetchall():
            st, c = str(row[0]), int(row[1])
            lines.append(f"| {st} | {c} |")
        lines.append("")

        cols_fill = [
            ("brand", "brand"),
            ("part_type", "part_type"),
            ("primary_make", "make (primary_make)"),
            ("primary_model", "model (primary_model)"),
            ("primary_body", "body (primary_body)"),
            ("side_axis", "side_axis"),
            ("engine", "engine"),
        ]
        lines.append("## Field fill rate (% non-empty)")
        lines.append("")
        lines.append("| field | % |")
        lines.append("|-------|--:|")
        for sql_col, label in cols_fill:
            row = conn.execute(
                f"SELECT {_nonempty_expr(sql_col)} AS filled FROM products"
            ).fetchone()
            filled = int(row[0] or 0)
            lines.append(f"| {label} | {_pct(filled, total)} |")

        yf = conn.execute(
            "SELECT SUM(CASE WHEN year_from IS NOT NULL AND year_from > 0 THEN 1 ELSE 0 END) AS filled FROM products"
        ).fetchone()
        yt = conn.execute(
            "SELECT SUM(CASE WHEN year_to IS NOT NULL AND year_to > 0 THEN 1 ELSE 0 END) AS filled FROM products"
        ).fetchone()
        lines.append(f"| year_from (>0) | {_pct(int(yf[0] or 0), total)} |")
        lines.append(f"| year_to (>0) | {_pct(int(yt[0] or 0), total)} |")
        lines.append("")

        parseable = int(
            conn.execute(
                "SELECT COUNT(*) FROM products WHERE supplier_raw_name LIKE '%' || ? || '%' || ? || '%'",
                ("{{", "}}"),
            ).fetchone()[0]
        )
        empty_raw = int(
            conn.execute(
                "SELECT COUNT(*) FROM products WHERE supplier_raw_name IS NULL OR TRIM(supplier_raw_name) = ''"
            ).fetchone()[0]
        )
        lines.append("## Supplier raw name")
        lines.append("")
        lines.append(f"- Contains `{{{{}}}}` (parseable-style): **{parseable}**")
        lines.append(f"- NULL or empty: **{empty_raw}**")
        lines.append("")

        lines.append("## Top 10 brands by count")
        lines.append("")
        lines.append("| brand | count |")
        lines.append("|-------|------:|")
        for row in conn.execute(
            """
            SELECT brand, COUNT(*) AS c
            FROM products
            GROUP BY brand
            ORDER BY c DESC
            LIMIT 10
            """
        ).fetchall():
            lines.append(f"| {row[0]} | {int(row[1])} |")
        lines.append("")

        lines.append("## Top 10 brands with empty part_type (D2 parsing candidates)")
        lines.append("")
        lines.append("| brand | count |")
        lines.append("|-------|------:|")
        for row in conn.execute(
            """
            SELECT brand, COUNT(*) AS c
            FROM products
            WHERE part_type IS NULL OR TRIM(part_type) = ''
            GROUP BY brand
            ORDER BY c DESC
            LIMIT 10
            """
        ).fetchall():
            lines.append(f"| {row[0]} | {int(row[1])} |")
        lines.append("")

        brand_filled = int(
            conn.execute(f"SELECT {_nonempty_expr('brand')} FROM products").fetchone()[0] or 0
        )
        part_filled = int(
            conn.execute(f"SELECT {_nonempty_expr('part_type')} FROM products").fetchone()[0] or 0
        )

    md = "\n".join(lines)
    print(md)

    brand_rate = _pct(brand_filled, total)
    part_rate = _pct(part_filled, total)
    print("\n--- Fill summary ---")
    print(f"brand fill:     {brand_rate}%")
    print(f"part_type fill: {part_rate}%")

    warn: list[str] = []
    if brand_rate < 50.0:
        warn.append(
            f"WARNING: brand fill {brand_rate}% < 50% - consider D2 naming parser + import fallback."
        )
    if part_rate < 10.0:
        warn.append(
            f"WARNING: part_type fill {part_rate}% < 10% - consider D2 naming parser + import fallback."
        )
    for w in warn:
        print(w)

    out = _ROOT / "docs" / "IMPORT_AUDIT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    full_md = md + "\n\n---\n\n" + "\n".join(warn) if warn else md
    out.write_text(full_md, encoding="utf-8")
    print(f"\nWritten: {out}")


if __name__ == "__main__":
    main()
