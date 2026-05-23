#!/usr/bin/env python3
"""
Pull Odoo product.category rows into local odoo_categories (CLI wrapper).

Run from project root:
    python scripts/sync_odoo_categories.py
    python scripts/sync_odoo_categories.py --chunk-size 100
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.schema_patches import apply_schema_patches  # noqa: E402
from app.services.odoo_catalog_sync import sync_odoo_categories  # noqa: E402
from app.services.odoo_client import OdooClient, OdooClientError  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync Odoo product.category → local odoo_categories cache.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=200,
        help="search_read page size (25–1000)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.chunk_size < 25 or args.chunk_size > 1000:
        print("ERROR: chunk-size must be between 25 and 1000")
        return 1

    apply_schema_patches(engine)

    try:
        client = OdooClient()
    except OdooClientError as exc:
        print(f"ERROR: Odoo client: {exc}")
        return 1

    db = SessionLocal()
    try:
        stats = sync_odoo_categories(db, client, chunk_size=args.chunk_size)
    except OdooClientError as exc:
        print(f"ERROR: Odoo sync failed: {exc}")
        return 1
    finally:
        db.close()

    print(
        f"Categories synced: total={stats['total']} "
        f"inserted={stats['inserted']} updated={stats['updated']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
