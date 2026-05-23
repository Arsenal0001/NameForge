"""
Safe Odoo sync pipeline: dry-run, source_hash idempotency.

``name_locked`` blocks TemplateEngine auto-regeneration elsewhere but does **not**
block Odoo push — locked products sync their stored ``generated_name`` when the hash
changed (e.g. after manual override).

All Odoo writes go through JSON-RPC ``execute_kw`` / ``write`` only (via :class:`OdooClient`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.product import Product
from app.schemas.sync import SyncLogEntry, SyncOdooResponse
from app.services.odoo_catalog_sync import utc_iso_timestamp
from app.services.odoo_client import OdooClient, OdooClientError
from app.services.template_service import generate_preview_for_product

logger = logging.getLogger(__name__)

SEARCH_KEYWORDS_FIELD = "x_search_keywords"
_MAX_SYNC_ERROR_LEN = 4000


def _truncate_sync_error(message: str) -> str:
    text = message.strip()
    if len(text) <= _MAX_SYNC_ERROR_LEN:
        return text
    return text[: _MAX_SYNC_ERROR_LEN - 1] + "…"


@dataclass
class _SyncCounters:
    pushed: int = 0
    skipped_locked: int = 0
    skipped_idempotent: int = 0
    skipped_invalid: int = 0
    errors: int = 0
    synced_product_ids: list[int] = field(default_factory=list)
    log: list[SyncLogEntry] = field(default_factory=list)
    pending_writes: list[tuple[int, Product, list[int], dict[str, str], str]] = field(
        default_factory=list,
    )


class SyncService:
    """Push approved local names to Odoo ``product.template`` with safety guards."""

    def __init__(
        self,
        session: Session,
        client: OdooClient,
        *,
        dry_run: bool | None = None,
        chunk_size: int = 50,
    ) -> None:
        self._session = session
        self._client = client
        self._dry_run = settings.DRY_RUN if dry_run is None else dry_run
        self._chunk_size = max(1, chunk_size)

    def sync_products(self, product_ids: list[int]) -> SyncOdooResponse:
        ordered_unique = list(dict.fromkeys(product_ids))
        counters = _SyncCounters()

        products = self._load_products(ordered_unique)
        by_id = {p.id: p for p in products}

        for pid in ordered_unique:
            product = by_id.get(pid)
            if product is None:
                counters.skipped_invalid += 1
                counters.log.append(
                    SyncLogEntry(product_id=pid, action="skipped_invalid", detail="not_found")
                )
                continue
            self._plan_product(product, counters)

        if not self._dry_run and counters.pending_writes:
            self._flush_writes(counters)

        return SyncOdooResponse(
            dry_run=self._dry_run,
            total=len(ordered_unique),
            pushed=counters.pushed,
            skipped_locked=counters.skipped_locked,
            skipped_idempotent=counters.skipped_idempotent,
            skipped_invalid=counters.skipped_invalid,
            errors=counters.errors,
            synced_product_ids=counters.synced_product_ids,
            log=counters.log,
        )

    def _load_products(self, product_ids: list[int]) -> list[Product]:
        if not product_ids:
            return []
        rows = (
            self._session.query(Product).filter(Product.id.in_(product_ids)).all()
        )
        return rows

    def _plan_product(self, product: Product, counters: _SyncCounters) -> None:
        if product.name_locked:
            name = (product.generated_name or "").strip()
            keywords = (product.search_keywords or "").strip()
            candidate_hash = (product.source_hash or "").strip()
        else:
            preview_result, _resolution = generate_preview_for_product(
                self._session, product
            )

            name = (product.generated_name or "").strip()
            keywords = (product.search_keywords or "").strip()
            candidate_hash = (product.source_hash or "").strip()

            if preview_result is not None:
                if not name:
                    name = (preview_result.name or "").strip()
                if not keywords:
                    keywords = (preview_result.search_keywords or "").strip()
                if preview_result.source_hash:
                    candidate_hash = preview_result.source_hash.strip()

        if not name:
            counters.skipped_invalid += 1
            counters.log.append(
                SyncLogEntry(
                    product_id=product.id,
                    action="skipped_invalid",
                    detail="missing_name",
                )
            )
            return

        odoo_raw = (product.odoo_product_id or "").strip()
        if not odoo_raw.isdigit():
            counters.skipped_invalid += 1
            counters.log.append(
                SyncLogEntry(
                    product_id=product.id,
                    action="skipped_invalid",
                    detail="missing_odoo_id",
                )
            )
            return

        stored_hash = (product.source_hash or "").strip()
        synced_at = (product.synced_at or "").strip()
        if candidate_hash and stored_hash and candidate_hash == stored_hash and synced_at:
            counters.skipped_idempotent += 1
            counters.log.append(
                SyncLogEntry(
                    product_id=product.id,
                    action="skipped_idempotent",
                    detail="source_hash_unchanged",
                )
            )
            return

        odoo_id = int(odoo_raw)
        values = {"name": name, SEARCH_KEYWORDS_FIELD: keywords}

        if self._dry_run:
            counters.pushed += 1
            counters.synced_product_ids.append(product.id)
            counters.log.append(
                SyncLogEntry(
                    product_id=product.id,
                    action="dry_run_would_push",
                    detail=f"odoo_id={odoo_id} name={name[:80]!r}",
                )
            )
            return

        counters.pending_writes.append((product.id, product, [odoo_id], values, candidate_hash))

    def _persist_sync_error(self, product_id: int, message: str) -> None:
        product = self._session.get(Product, product_id)
        if product is None:
            return
        product.last_sync_error = _truncate_sync_error(message)
        self._session.add(product)
        try:
            self._session.commit()
        except Exception:
            logger.exception("Failed to persist last_sync_error for product_id=%s", product_id)
            self._session.rollback()

    def _flush_writes(self, counters: _SyncCounters) -> None:
        for i in range(0, len(counters.pending_writes), self._chunk_size):
            chunk = counters.pending_writes[i : i + self._chunk_size]
            batch = [(odoo_ids, values) for _, _, odoo_ids, values, _ in chunk]
            try:
                self._client.batch_write("product.template", batch)
            except OdooClientError as exc:
                logger.error("Odoo batch_write failed: %s", exc)
                error_text = str(exc)
                for product_id, _, _, _, _ in chunk:
                    counters.errors += 1
                    counters.log.append(
                        SyncLogEntry(
                            product_id=product_id,
                            action="error",
                            detail=error_text,
                        )
                    )
                self._session.rollback()
                for product_id, _, _, _, _ in chunk:
                    self._persist_sync_error(product_id, error_text)
                continue

            now = utc_iso_timestamp()
            for product_id, product, _odoo_ids, values, candidate_hash in chunk:
                product.synced_at = now
                product.last_sync_error = None
                if candidate_hash:
                    product.source_hash = candidate_hash
                if not (product.generated_name or "").strip():
                    product.generated_name = values.get("name")
                if not (product.search_keywords or "").strip():
                    product.search_keywords = values.get(SEARCH_KEYWORDS_FIELD) or None
                self._session.add(product)
                counters.pushed += 1
                counters.synced_product_ids.append(product_id)
                counters.log.append(
                    SyncLogEntry(
                        product_id=product_id,
                        action="pushed",
                        detail="odoo_write_ok",
                    )
                )
            try:
                self._session.commit()
            except Exception as exc:
                logger.exception("Failed to commit sync metadata")
                self._session.rollback()
                error_text = f"db_commit:{exc}"
                for product_id, _, _, _, _ in chunk:
                    counters.errors += 1
                    counters.log.append(
                        SyncLogEntry(
                            product_id=product_id,
                            action="error",
                            detail=error_text,
                        )
                    )
                    self._persist_sync_error(product_id, error_text)
