"""
Time a review-batch sync (same rules as Sync page): up to N products in ``review``,
``candidate_hash != source_hash``, then ``approve_and_sync_execute`` with DRY_RUN off.

Usage (project root):
  set DRY_RUN=false in .env (or env) for real PUTs
  python scripts/run_batch_sync_review_timing.py --limit 50
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.config import validate_startup_env  # noqa: E402
from src.db import get_conn, init_db  # noqa: E402
from src.directory_cache import DirectoryCache  # noqa: E402
from src.moysklad_client import MoySkladClient  # noqa: E402
from src.product_workflow import (  # noqa: E402
    approve_and_sync_execute,
    fitment_dicts_for_product,
    load_product_for_workflow,
    run_generate_name,
)

_DEFAULT_MS_BASE_URL = "https://api.moysklad.ru/remap/1.2"


def _token() -> str:
    return (
        (os.environ.get("MS_TOKEN") or "")
        or (os.environ.get("MS_API_TOKEN") or "")
        or (os.environ.get("MOYSKLAD_TOKEN") or "")
    ).strip()


def main() -> int:
    p = argparse.ArgumentParser(description="Batch sync timing for review queue")
    p.add_argument("--limit", type=int, default=50, help="Max products to PUT (default 50)")
    args = p.parse_args()
    limit = max(1, min(500, int(args.limit)))

    load_dotenv(_ROOT / ".env")
    load_dotenv()
    validate_startup_env()
    init_db()

    token = _token()
    if not token:
        print("No API token in env (MS_TOKEN / MS_API_TOKEN / MOYSKLAD_TOKEN).")
        return 1

    base_url = (os.environ.get("MS_BASE_URL") or _DEFAULT_MS_BASE_URL).strip()
    client = MoySkladClient(token, base_url, dry_run=False)
    dc = DirectoryCache(client)

    candidates: list[tuple[int, str, str, str]] = []
    with get_conn() as conn:
        conn.row_factory = None
        cur = conn.execute(
            """
            SELECT id FROM products
            WHERE generation_status = 'review'
              AND name_locked = 0
              AND TRIM(COALESCE(ms_product_id, '')) != ''
            ORDER BY id
            """
        )
        for (pid_raw,) in cur.fetchall():
            pid = int(pid_raw)
            product = load_product_for_workflow(pid)
            if not product:
                continue
            fitments = fitment_dicts_for_product(pid)
            gen, chash = run_generate_name(product, fitments)
            if gen.status != "generated":
                continue
            if chash == str(product.get("source_hash") or ""):
                continue
            candidates.append((pid, gen.name, gen.description, chash))
            if len(candidates) >= limit:
                break

    if not candidates:
        print("No review products with changed hash and generated name (check queue / previews).")
        return 0

    n = len(candidates)
    t0 = time.perf_counter()
    ok = err = 0
    first_log: str | None = None
    for i, (pid, name, desc, chash) in enumerate(candidates):
        product = load_product_for_workflow(pid)
        if not product:
            err += 1
            continue
        code, detail = approve_and_sync_execute(
            client,
            product,
            name,
            chash,
            desc,
            dry_run=False,
            directory_cache=dc,
        )
        if code == "ok":
            ok += 1
        else:
            err += 1
            if first_log is None:
                first_log = f"id={pid} code={code} detail={detail!r}"
        if i < n - 1:
            time.sleep(0.1)
    elapsed = time.perf_counter() - t0
    print(f"batch_size={n} ok={ok} err={err} elapsed_sec={elapsed:.3f}")
    if first_log:
        print(f"first_issue: {first_log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
