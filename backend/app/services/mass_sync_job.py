"""Mass push of generated product names to Odoo (SyncService, no CLI UI)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from app.core.config import settings
from app.core.database import SessionLocal
from app.schemas.sync import SyncOdooResponse
from app.services.odoo_client import OdooClient, OdooClientError
from app.services.sync_queue import collect_sync_candidate_ids
from app.services.sync_service import SyncService

logger = logging.getLogger(__name__)


@dataclass
class MassSyncTotals:
    batches: int = 0
    candidates: int = 0
    total: int = 0
    pushed: int = 0
    skipped_locked: int = 0
    skipped_idempotent: int = 0
    skipped_invalid: int = 0
    errors: int = 0
    synced_product_ids: list[int] = field(default_factory=list)

    def absorb(self, response: SyncOdooResponse) -> None:
        self.total += response.total
        self.pushed += response.pushed
        self.skipped_locked += response.skipped_locked
        self.skipped_idempotent += response.skipped_idempotent
        self.skipped_invalid += response.skipped_invalid
        self.errors += response.errors
        self.synced_product_ids.extend(response.synced_product_ids)


def _chunk_ids(ids: list[int], size: int) -> list[list[int]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]


def run_mass_sync_to_odoo(
    *,
    batch_size: int = 100,
    dry_run: bool | None = None,
    limit: int | None = None,
    odoo_chunk_size: int = 50,
    on_progress: Callable[[int, int], None] | None = None,
) -> MassSyncTotals:
    """
    Push sync candidates to Odoo in batches via :class:`SyncService`.

    Uses its own SQLAlchemy session. Respects ``settings.DRY_RUN`` unless
    ``dry_run`` is passed explicitly.
    """
    if batch_size < 1 or batch_size > 2000:
        raise ValueError("batch_size must be between 1 and 2000")

    effective_dry_run = settings.DRY_RUN if dry_run is None else dry_run
    client = OdooClient()
    ok, message = client.test_connection()
    if not ok:
        raise OdooClientError(f"Odoo connection failed: {message}")

    db = SessionLocal()
    totals = MassSyncTotals()
    try:
        candidate_ids = collect_sync_candidate_ids(db)
        if limit is not None:
            candidate_ids = candidate_ids[:limit]

        totals.candidates = len(candidate_ids)
        if on_progress is not None:
            on_progress(0, totals.candidates)
        if not candidate_ids:
            logger.info(
                "Mass Odoo sync: no candidates (dry_run=%s)", effective_dry_run
            )
            return totals

        batches = _chunk_ids(candidate_ids, batch_size)
        totals.batches = len(batches)
        service = SyncService(
            db, client, dry_run=effective_dry_run, chunk_size=odoo_chunk_size
        )

        processed = 0
        for index, batch in enumerate(batches, start=1):
            result = service.sync_products(batch)
            totals.absorb(result)
            processed += len(batch)
            if on_progress is not None:
                on_progress(processed, totals.candidates)
            logger.info(
                "Mass Odoo sync batch %s/%s: pushed=%s skipped_locked=%s "
                "skipped_idempotent=%s errors=%s dry_run=%s",
                index,
                len(batches),
                result.pushed,
                result.skipped_locked,
                result.skipped_idempotent,
                result.errors,
                result.dry_run,
            )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    logger.info(
        "Mass Odoo sync finished: candidates=%s pushed=%s errors=%s dry_run=%s",
        totals.candidates,
        totals.pushed,
        totals.errors,
        effective_dry_run,
    )
    return totals
