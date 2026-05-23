#!/usr/bin/env python3
"""
Mass-push generated product names to Odoo via :class:`SyncService`.

Respects ``DRY_RUN`` from ``.env`` unless ``--force-apply`` is passed.

Run from project root:
    python scripts/mass_sync_to_odoo.py
    python scripts/mass_sync_to_odoo.py --batch-size 150
    python scripts/mass_sync_to_odoo.py --force-apply
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

from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.schema_patches import apply_schema_patches  # noqa: E402
from app.services.mass_sync_job import run_mass_sync_to_odoo  # noqa: E402
from app.services.odoo_client import OdooClient, OdooClientError  # noqa: E402
from app.services.sync_queue import collect_sync_candidate_ids  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mass sync generated names to Odoo via SyncService.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Product ids per SyncService call (default: 100)",
    )
    parser.add_argument(
        "--force-apply",
        action="store_true",
        help="Override DRY_RUN and perform live Odoo writes for this run",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N candidate products (debug)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_size < 1 or args.batch_size > 2000:
        print("ERROR: --batch-size must be between 1 and 2000")
        return 1

    apply_schema_patches(engine)

    dry_run = settings.DRY_RUN
    if args.force_apply:
        dry_run = False

    mode = "DRY-RUN" if dry_run else "LIVE"
    print(f"Mass Odoo sync [{mode}] — batch_size={args.batch_size}")

    if args.force_apply and settings.DRY_RUN:
        print("WARNING: --force-apply overrides DRY_RUN=true for this run only.")

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
    try:
        candidate_ids = collect_sync_candidate_ids(db)
    finally:
        db.close()

    if args.limit is not None:
        candidate_ids = candidate_ids[: args.limit]

    if not candidate_ids:
        print("No sync candidates found.")
        return 0

    batch_count = (len(candidate_ids) + args.batch_size - 1) // args.batch_size
    started = time.perf_counter()

    with Progress(
        TextColumn("[bold blue]Odoo sync"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        transient=False,
    ) as progress:
        task = progress.add_task("batches", total=batch_count)
        totals = run_mass_sync_to_odoo(
            batch_size=args.batch_size,
            dry_run=dry_run,
            limit=args.limit,
        )
        progress.update(task, completed=batch_count)

    elapsed = time.perf_counter() - started
    print(f"\n=== Mass sync summary ({mode}, {elapsed:.1f}s) ===")
    print(f"Candidates selected:     {totals.candidates}")
    print(f"Batches processed:     {totals.batches}")
    print(f"Products in batches:   {totals.total}")
    print(f"Pushed / would push:   {totals.pushed}")
    print(f"Skipped (locked):      {totals.skipped_locked}")
    print(f"Skipped (idempotent):  {totals.skipped_idempotent}")
    print(f"Skipped (invalid):     {totals.skipped_invalid}")
    print(f"Errors:                {totals.errors}")
    print(f"Synced product ids:    {len(totals.synced_product_ids)}")
    return 0 if totals.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
