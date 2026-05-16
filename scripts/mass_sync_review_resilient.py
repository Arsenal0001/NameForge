"""
Production mass sync: review → МойСклад (DRY off, single DirectoryCache, resilient PUT).

Iterator (per spec):
  SELECT id FROM products
  WHERE generation_status = 'review' AND name_locked = 0
  ORDER BY id

After run:
  UPDATE products SET error_message = NULL WHERE generation_status = 'approved';

Usage (project root):
  python scripts/mass_sync_review_resilient.py
  python scripts/mass_sync_review_resilient.py --max 100   # test slice
  python scripts/mass_sync_review_resilient.py --limit 500  # alias of --max
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.config import validate_startup_env  # noqa: E402
from src.db import get_conn, init_db  # noqa: E402
from src.directory_cache import DirectoryCache  # noqa: E402
from src.moysklad_client import MoySkladAPIError, MoySkladClient  # noqa: E402
from src.product_workflow import (  # noqa: E402
    approve_and_sync_execute,
    is_moysklad_rate_limit_error,
    fitment_dicts_for_product,
    load_product_for_workflow,
    run_generate_name,
)

logger = logging.getLogger(__name__)

_DEFAULT_MS_BASE_URL = "https://api.moysklad.ru/remap/1.2"
_LAST_SYNC_LOG = _ROOT / "logs" / "last_sync.log"

_TRANSIENT_NET = (
    requests.exceptions.ConnectionError,
    requests.exceptions.ConnectTimeout,
    requests.exceptions.ReadTimeout,
    requests.exceptions.Timeout,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _token() -> str:
    return (
        (os.environ.get("MS_TOKEN") or "")
        or (os.environ.get("MS_API_TOKEN") or "")
        or (os.environ.get("MOYSKLAD_TOKEN") or "")
    ).strip()


def _append_log_success(article: str, product_id: int) -> None:
    art = (article or "").replace("\n", " ").replace("\r", " ").strip()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] SUCCESS: {art} {product_id}\n"
    _LAST_SYNC_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_LAST_SYNC_LOG, "a", encoding="utf-8") as f:
        f.write(line)


def _warm_directory_cache(dc: DirectoryCache) -> None:
    du = dc.brand_directory_uuid()
    if du:
        dc.load(du)
        n_el = len(getattr(dc, "_cache", {}).get(du) or [])
        logger.info(f"DirectoryCache: warmed once — {du} ({n_el} element(s)).")
    else:
        logger.info("DirectoryCache: brand dictionary UUID not resolved (check attr_map / API).")


def _sql_ids() -> list[int]:
    sql = """
        SELECT id FROM products
        WHERE generation_status = 'review' AND name_locked = 0
        ORDER BY id
    """
    with get_conn() as conn:
        return [int(r[0]) for r in conn.execute(sql).fetchall()]


def _sync_with_retries(
    client: MoySkladClient,
    product: dict,
    gen_name: str,
    chash: str,
    gen_desc: str,
    dc: DirectoryCache,
) -> tuple[str, str | None]:
    """
    429: up to 5 attempts, exponential backoff. Network transient: one failure, 5s sleep, then error.
    """
    attempt_429 = 0
    while True:
        try:
            return approve_and_sync_execute(
                client,
                product,
                gen_name,
                chash,
                gen_desc,
                dry_run=False,
                directory_cache=dc,
                re_raise_rate_limit=True,
            )
        except MoySkladAPIError as e:
            if is_moysklad_rate_limit_error(e) and attempt_429 < 5:
                attempt_429 += 1
                sleep_time = 2 ** attempt_429  # 2, 4, 8, 16, 32
                logger.warning("Rate limited (429). Backing off for %ss (attempt %s/5)", sleep_time, attempt_429)
                time.sleep(sleep_time)
                continue
            return "error", str(e)
        except _TRANSIENT_NET as e:
            time.sleep(5.0)
            return "error", f"transient:{type(e).__name__}: {e}"
        except OSError as e:
            time.sleep(5.0)
            return "error", f"transient:OSError: {e}"


def _post_sync_cleanup() -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE products SET error_message = NULL WHERE generation_status = 'approved'"
        )
        return cur.rowcount if cur.rowcount is not None else 0


def main() -> int:
    p = argparse.ArgumentParser(description="Production review → MoySklad sync")
    p.add_argument(
        "--max",
        "--limit",
        type=int,
        default=None,
        dest="max",
        help="Max product ids to process from iterator (default: all). Same as --limit.",
    )
    args = p.parse_args()

    log_path = _ROOT / "logs" / "sync_final.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )

    load_dotenv(_ROOT / ".env")
    load_dotenv()
    validate_startup_env()
    init_db()

    token = _token()
    if not token:
        logger.info("No API token in env (MS_TOKEN / MS_API_TOKEN / MOYSKLAD_TOKEN).")
        return 1

    base_url = (os.environ.get("MS_BASE_URL") or _DEFAULT_MS_BASE_URL).strip()
    client = MoySkladClient(token, base_url, dry_run=False)
    dc = DirectoryCache(client)
    _warm_directory_cache(dc)

    rows = _sql_ids()
    if args.max is not None:
        rows = rows[: max(0, int(args.max))]
    total = len(rows)
    if total == 0:
        logger.info("Iterator returned 0 rows (no review, name_unlocked=0).")
        n = _post_sync_cleanup()
        logger.info(f"Cleanup: error_message cleared for {n} approved row(s).")
        return 0

    t0 = time.perf_counter()
    n_ok = 0
    n_err = 0
    n_skip = 0
    t_sync_work = 0.0
    n_put_attempts = 0

    for i, pid in enumerate(rows, start=1):
        product = load_product_for_workflow(pid)
        if not product:
            logger.info(f"[{i}/{total}] id={pid} Article: ? Status: missing_row")
            n_skip += 1
            continue
        art = str(product.get("article") or "")

        fitments = fitment_dicts_for_product(pid)
        gen, candidate_hash = run_generate_name(product, fitments)
        if gen.status != "generated":
            logger.info(f"[{i}/{total}] Article: {art!r} Status: gen_not_ok ({gen.status})")
            n_skip += 1
            continue

        src = str(product.get("source_hash") or "")
        if candidate_hash == src:
            logger.info(f"[{i}/{total}] Article: {art!r} Status: no_change")
            n_skip += 1
            continue

        t_one = time.perf_counter()
        n_put_attempts += 1
        code, detail = _sync_with_retries(
            client,
            product,
            gen.name,
            candidate_hash,
            gen.description,
            dc,
        )
        t_sync_work += time.perf_counter() - t_one

        if code == "ok":
            n_ok += 1
            _append_log_success(art, pid)
            logger.info(f"[{i}/{total}] Article: {art!r} Status: ok (PUT)")
        else:
            n_err += 1
            logger.info(f"[{i}/{total}] Article: {art!r} Status: {code} — {detail!r}")

    elapsed = time.perf_counter() - t0
    n_clean = _post_sync_cleanup()

    avg_per_row = elapsed / max(1, total)
    avg_per_put = t_sync_work / max(1, n_put_attempts)

    logger.info("---")
    logger.info(f"Done. iterator_rows={total} put_attempts={n_put_attempts}")
    logger.info(f"OK (2xx from HTTP layer / workflow ok): {n_ok}")
    logger.info(f"Failed (error return or retried out): {n_err}")
    logger.info(f"Skipped (no data / not generated / no hash change): {n_skip}")
    logger.info(f"Wall time: {elapsed:.3f}s; avg s/iterator row: {avg_per_row:.4f}; avg s/PUT attempt: {avg_per_put:.4f}")
    logger.info(f"Post-sync: cleared error_message on {n_clean} approved row(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
