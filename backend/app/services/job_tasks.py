"""Background runners for dashboard ETL jobs (isolated DB sessions)."""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.database import SessionLocal, engine
from app.core.schema_patches import apply_schema_patches
from app.services.catalog_jsonl_enrichment import (
    DEFAULT_JSONL,
    run_catalog_jsonl_enrichment,
)
from app.services.job_lock import JobKind, release
from app.services.job_progress import job_progress
from app.services.mass_sync_job import run_mass_sync_to_odoo
from app.services.odoo_client import OdooClient, OdooClientError
from app.services.product_catalog_sync import sync_products_from_odoo

logger = logging.getLogger(__name__)

DEFAULT_SYNC_CHUNK_SIZE = 500
DEFAULT_ENRICH_BATCH_SIZE = 100
DEFAULT_MASS_SYNC_BATCH_SIZE = 100


def run_sync_from_odoo_job(*, chunk_size: int = DEFAULT_SYNC_CHUNK_SIZE) -> None:
    kind = JobKind.SYNC_FROM_ODOO
    job_progress.start(kind)
    db = SessionLocal()
    try:
        apply_schema_patches(engine)
        client = OdooClient()
        ok, message = client.test_connection()
        if not ok:
            job_progress.fail(kind, f"Odoo connection failed: {message}")
            logger.error("sync-from-odoo job: Odoo connection failed: %s", message)
            return

        def on_progress(current: int, total: int) -> None:
            if total <= 0:
                return
            job_progress.update(kind, current, total_items=total)

        stats = sync_products_from_odoo(
            db,
            client,
            chunk_size=chunk_size,
            on_progress=on_progress,
        )
        processed = int(stats.get("processed", 0))
        total = int(stats.get("total_odoo", 0))
        job_progress.update(kind, processed, total_items=total, force=True)
        job_progress.complete(kind, processed_items=processed)
        logger.info("sync-from-odoo job complete: %s", stats)
    except OdooClientError as exc:
        job_progress.fail(kind, str(exc))
        logger.exception("sync-from-odoo job: Odoo error")
    except Exception as exc:
        job_progress.fail(kind, str(exc) or "sync-from-odoo job failed")
        logger.exception("sync-from-odoo job failed")
        db.rollback()
    finally:
        db.close()
        release(kind)


def run_enrich_job(
    *,
    jsonl_path: Path = DEFAULT_JSONL,
    batch_size: int = DEFAULT_ENRICH_BATCH_SIZE,
) -> None:
    kind = JobKind.ENRICH
    job_progress.start(kind)
    try:
        stats = run_catalog_jsonl_enrichment(
            jsonl_path,
            dry_run=False,
            batch_size=batch_size,
            on_progress=lambda current, total: job_progress.update(
                kind, current, total_items=total
            ),
        )
        job_progress.update(
            kind,
            stats.jsonl_rows if stats.jsonl_rows else 0,
            total_items=stats.jsonl_rows,
            force=True,
        )
        job_progress.complete(kind, processed_items=stats.jsonl_rows)
    except FileNotFoundError:
        job_progress.fail(kind, f"JSONL not found at {jsonl_path}")
        logger.error("enrich job: JSONL not found at %s", jsonl_path)
    except Exception as exc:
        job_progress.fail(kind, str(exc) or "enrich job failed")
        logger.exception("enrich job failed")
    finally:
        release(kind)


def run_push_to_odoo_job(*, batch_size: int = DEFAULT_MASS_SYNC_BATCH_SIZE) -> None:
    kind = JobKind.PUSH_TO_ODOO
    job_progress.start(kind)
    try:
        totals = run_mass_sync_to_odoo(
            batch_size=batch_size,
            on_progress=lambda current, total: job_progress.update(
                kind, current, total_items=total
            ),
        )
        processed = totals.candidates
        job_progress.update(kind, processed, total_items=processed, force=True)
        if totals.candidates == 0:
            job_progress.complete(kind, processed_items=0)
        elif totals.errors > 0:
            job_progress.fail(
                kind,
                f"Mass Odoo push finished with {totals.errors} error(s)",
            )
        else:
            job_progress.complete(kind, processed_items=processed)
    except OdooClientError as exc:
        job_progress.fail(kind, str(exc))
        logger.exception("push-to-odoo job: Odoo error")
    except Exception as exc:
        job_progress.fail(kind, str(exc) or "push-to-odoo job failed")
        logger.exception("push-to-odoo job failed")
    finally:
        release(kind)
