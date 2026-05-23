#!/usr/bin/env python3
"""
Pull Odoo ``product.template`` catalog into local ``products`` (NameForge 2.0).

Uses chunked JSON-RPC ``search_read`` via :class:`OdooClient` — no XML-RPC.

Run from project root:
    python scripts/sync_catalog_from_odoo.py
    python scripts/sync_catalog_from_odoo.py --chunk-size 500
    python scripts/sync_catalog_from_odoo.py --include-inactive
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
if str(_ROOT) not in sys.path:
    sys.path.append(str(_ROOT))

import src.db as legacy_db  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.schema_patches import apply_schema_patches  # noqa: E402
from app.services.odoo_client import OdooClient, OdooClientError  # noqa: E402
from app.services.product_catalog_sync import sync_products_from_odoo  # noqa: E402


class ConsoleProgress:
    """Lightweight terminal progress bar (no extra dependencies)."""

    def __init__(self, total: int, *, width: int = 32) -> None:
        self.total = max(total, 0)
        self.width = width
        self._last_line_len = 0

    def update(self, current: int, total: int) -> None:
        total = total or self.total
        if total <= 0:
            return
        current = min(current, total)
        ratio = current / total
        filled = int(self.width * ratio)
        bar = "=" * filled + ">" * (1 if filled < self.width and filled > 0 else 0)
        bar = bar.ljust(self.width, " ")
        line = f"\r[{bar}] {current}/{total} ({ratio * 100:5.1f}%)"
        pad = max(self._last_line_len - len(line), 0)
        sys.stdout.write(line + " " * pad)
        sys.stdout.flush()
        self._last_line_len = len(line)
        if current >= total:
            sys.stdout.write("\n")
            sys.stdout.flush()

    def close(self) -> None:
        if self._last_line_len:
            sys.stdout.write("\n")
            sys.stdout.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync Odoo product.template → local products table.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="search_read page size (25–1000, default: 500)",
    )
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include archived (active=false) templates",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.chunk_size < 25 or args.chunk_size > 1000:
        print("ERROR: --chunk-size must be between 25 and 1000")
        return 1

    legacy_db.init_db()
    apply_schema_patches(engine)

    try:
        client = OdooClient()
    except OdooClientError as exc:
        print(f"ERROR: Odoo client: {exc}")
        return 1

    ok, message = client.test_connection()
    if not ok:
        print(f"ERROR: Odoo connection failed: {message}")
        return 1
    print(f"Connected to Odoo as: {message}")

    db = SessionLocal()
    progress: ConsoleProgress | None = None
    started = time.perf_counter()

    def on_progress(current: int, total: int) -> None:
        nonlocal progress
        if progress is None:
            progress = ConsoleProgress(total)
        progress.update(current, total)

    try:
        stats = sync_products_from_odoo(
            db,
            client,
            chunk_size=args.chunk_size,
            include_inactive=args.include_inactive,
            on_progress=on_progress,
        )
    except OdooClientError as exc:
        print(f"\nERROR: Odoo sync failed: {exc}")
        return 1
    finally:
        if progress is not None:
            progress.close()
        db.close()

    elapsed = time.perf_counter() - started
    print(
        f"\nCatalog sync complete in {elapsed:.1f}s: "
        f"odoo_total={stats['total_odoo']} "
        f"processed={stats['processed']} "
        f"inserted={stats['inserted']} "
        f"updated={stats['updated']}"
    )
    if stats["skipped_inactive"]:
        print(f"Skipped inactive rows: {stats['skipped_inactive']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
