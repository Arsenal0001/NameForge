#!/usr/bin/env python3
"""
Mass-enrich local NameForge catalog from ``odoo_master_catalog.jsonl``.

Run from project root:
    python scripts/enrich_catalog_from_jsonl.py              # dry-run (default)
    python scripts/enrich_catalog_from_jsonl.py --apply    # write to DB
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
if str(_ROOT) not in sys.path:
    sys.path.append(str(_ROOT))

from app.services.catalog_jsonl_enrichment import (  # noqa: E402
    DEFAULT_JSONL,
    EnrichmentStats,
    run_catalog_jsonl_enrichment,
)


def print_report(stats: EnrichmentStats, *, dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n=== Catalog enrichment ({mode}) ===")
    print(f"JSONL rows read:              {stats.jsonl_rows}")
    print(f"JSONL rows with default_code: {stats.jsonl_with_code}")
    print(f"Matched JSONL rows:           {stats.matched_rows}")
    print(f"Unique local products:        {stats.matched_products}")
    print(f"Ready (fitment):              {stats.ready_fitment}")
    print(f"Ready (universal):            {stats.ready_universal}")
    print(f"Skipped (no DB match):        {stats.skipped_no_match}")
    print(f"Skipped (incomplete fitment): {stats.skipped_incomplete}")
    print(f"Skipped (name_locked):        {stats.skipped_locked}")
    if not dry_run:
        print(f"Applied successfully:       {stats.applied}")
        print(f"Generation errors:          {stats.generation_errors}")

    if dry_run:
        examples = stats.preview_fitment + stats.preview_universal
        if examples:
            print("\nPreview examples (no DB writes):")
            for idx, example in enumerate(examples[:5], 1):
                print(f"  [{idx}] code={example['default_code']}")
                print(f"      part_type: {example['part_type']}")
                print(f"      fitment:   {example['make']} / {example['model']}")
                print(f"      preview:   {example['preview_name']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich local products from odoo_master_catalog.jsonl.",
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=DEFAULT_JSONL,
        help=f"Path to master catalog JSONL (default: {DEFAULT_JSONL})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to DB (default: dry-run statistics only)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Commit every N matched products when --apply (default: 100)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most N JSONL rows (debug)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dry_run = not args.apply
    jsonl_path = args.jsonl.resolve()

    if not jsonl_path.is_file():
        print(f"ERROR: JSONL not found: {jsonl_path}")
        return 1

    if args.batch_size < 1:
        print("ERROR: --batch-size must be >= 1")
        return 1

    stats = run_catalog_jsonl_enrichment(
        jsonl_path,
        dry_run=dry_run,
        batch_size=args.batch_size,
        limit=args.limit,
    )
    print_report(stats, dry_run=dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
