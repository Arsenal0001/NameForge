#!/usr/bin/env python3
"""
Canary E2E pipeline: extract 5 SKUs from Odoo → JSONL enrich → live push via SyncService.

Run from project root:
    python scripts/run_canary_test.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))
if str(_ROOT) not in sys.path:
    sys.path.append(str(_ROOT))

# Replace with real default_code values before running against production Odoo.
TARGET_CODES = ["CODE1", "CODE2", "CODE3", "CODE4", "CODE5"]

import src.db as legacy_db  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.schema_patches import apply_schema_patches  # noqa: E402
from app.models.product import Product  # noqa: E402
from app.services.catalog_jsonl_enrichment import (  # noqa: E402
    DEFAULT_JSONL,
    EnrichmentStats,
    _process_row,
    build_product_index,
    code_variants,
    extract_default_code,
    load_jsonl_rows,
)
from app.services.odoo_client import OdooClient, OdooClientError  # noqa: E402
from app.services.product_catalog_sync import (  # noqa: E402
    READ_FIELDS,
    _default_code,
    _load_category_labels,
    _many2one_id,
    _resolve_part_type,
    _text,
    ensure_odoo_import_templates,
    utc_iso_timestamp,
)
from app.services.sync_service import SyncService  # noqa: E402
from app.services.template_service import (  # noqa: E402
    generate_preview_for_product,
    get_template_engine,
)
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402
from sqlalchemy import or_, select  # noqa: E402


@dataclass
class CanaryProductState:
    default_code: str
    product_id: int | None = None
    original_odoo_name: str = ""
    generated_name: str = ""
    sync_status: str = "Pending"
    error_log: str = ""
    enrich_warnings: list[str] = field(default_factory=list)


def _allowed_code_variants(codes: list[str]) -> set[str]:
    allowed: set[str] = set()
    for code in codes:
        stripped = code.strip()
        if not stripped:
            continue
        allowed.add(stripped)
        allowed |= code_variants(stripped)
    return allowed


def _resolve_state_by_code(
    states: dict[str, CanaryProductState],
    code: str,
) -> CanaryProductState | None:
    variants = code_variants(code)
    for variant in variants:
        if variant in states:
            return states[variant]
    if code in states:
        return states[code]
    return None


def extract_target_products(
    session,
    client: OdooClient,
    target_codes: list[str],
    states: dict[str, CanaryProductState],
) -> None:
    ensure_odoo_import_templates(session)
    category_labels = _load_category_labels(session)

    domain = [("default_code", "in", target_codes)]
    rows = client.search_read(
        "product.template",
        domain,
        READ_FIELDS,
        order="default_code",
    )

    found_codes: set[str] = set()
    now = utc_iso_timestamp()

    for row in rows:
        code = _default_code(row)
        state = _resolve_state_by_code(states, code)
        if state is None:
            continue

        found_codes.add(state.default_code)
        odoo_id = int(row["id"])
        odoo_key = str(odoo_id)
        odoo_name = _text(row.get("name"))
        state.original_odoo_name = odoo_name

        categ_id = _many2one_id(row.get("categ_id"))
        category_label = category_labels.get(categ_id, "") if categ_id else ""

        product = session.scalar(
            select(Product).where(Product.odoo_product_id == odoo_key)
        )
        if product is None:
            code_owner = session.scalar(
                select(Product.id).where(
                    Product.external_code == code,
                    Product.odoo_product_id != odoo_key,
                )
            )
            if code_owner is not None:
                code = f"{code}-odoo-{odoo_id}"

            product = Product(
                odoo_product_id=odoo_key,
                external_code=code,
                article=code,
                brand="UNKNOWN",
                part_type=_resolve_part_type(categ_id, category_labels),
                applicability_type="universal",
                template_key="universal_base",
                template_version="v1",
                generation_status="new",
                name_locked=False,
                source_hash="",
                created_at=now,
                updated_at=now,
            )
            session.add(product)

        product.external_code = code
        product.article = code
        product.supplier_raw_name = odoo_name or product.supplier_raw_name
        product.product_folder = category_label or product.product_folder
        if product.part_type in ("", "Товар"):
            product.part_type = _resolve_part_type(categ_id, category_labels)
        product.updated_at = now
        session.flush()
        state.product_id = product.id

    session.commit()

    for code, state in states.items():
        if code not in found_codes:
            state.sync_status = "Error"
            state.error_log = "Not found in Odoo (default_code search returned no row)"


def enrich_target_products(
    session,
    jsonl_path: Path,
    target_codes: list[str],
    states: dict[str, CanaryProductState],
) -> EnrichmentStats:
    allowed = _allowed_code_variants(target_codes)
    stats = EnrichmentStats()

    rows = [
        row
        for row in load_jsonl_rows(jsonl_path)
        if _row_matches_targets(row, allowed)
    ]
    stats.jsonl_rows = len(rows)

    get_template_engine().ensure_loaded(session)

    products = session.scalars(
        select(Product).where(
            or_(
                Product.external_code.in_(list(allowed)),
                Product.article.in_(list(allowed)),
            )
        )
    ).all()
    product_index = build_product_index(list(products))
    state_by_product_id = {
        state.product_id: state for state in states.values() if state.product_id is not None
    }
    matched_product_ids: set[int] = set()
    pending_since_commit = 0

    for row in rows:
        default_code = extract_default_code(row)
        if not default_code:
            continue
        stats.jsonl_with_code += 1

        product = None
        for variant in code_variants(default_code):
            product = product_index.get(variant)
            if product is not None:
                break
        if product is None:
            stats.skipped_no_match += 1
            continue

        state = state_by_product_id.get(product.id)
        if state is None:
            continue

        stats.matched_rows += 1
        matched_product_ids.add(product.id)
        _process_row(session, product, row, dry_run=False, stats=stats)
        pending_since_commit += 1
        if pending_since_commit >= 5:
            session.commit()
            pending_since_commit = 0

    if pending_since_commit:
        session.commit()

    stats.matched_products = len(matched_product_ids)

    for state in state_by_product_id.values():
        if state.product_id not in matched_product_ids:
            state.sync_status = "Error"
            state.error_log = "No matching JSONL row for this default_code"
    return stats


def _row_matches_targets(row: dict, allowed: set[str]) -> bool:
    code = extract_default_code(row)
    if not code:
        return False
    return bool(code_variants(code) & allowed)


def load_target_products(
    session,
    client: OdooClient,
    states: dict[str, CanaryProductState],
    *,
    force_apply: bool = True,
) -> None:
    product_ids = [
        state.product_id
        for state in states.values()
        if state.product_id is not None and not state.error_log
    ]
    if not product_ids:
        return

    dry_run = False if force_apply else settings.DRY_RUN
    if force_apply and settings.DRY_RUN:
        Console().print(
            "[yellow]WARNING:[/yellow] force_apply overrides DRY_RUN=true for canary push.",
        )

    service = SyncService(session, client, dry_run=dry_run)
    result = service.sync_products(product_ids)
    log_by_product = {entry.product_id: entry for entry in result.log}

    for state in states.values():
        if state.product_id is None:
            continue
        entry = log_by_product.get(state.product_id)
        if entry is None:
            if not state.error_log:
                state.sync_status = "Error"
                state.error_log = "No sync log entry returned"
            continue

        if entry.action == "pushed":
            state.sync_status = "Success"
            state.error_log = ""
        elif entry.action == "dry_run_would_push" and dry_run:
            state.sync_status = "Success"
            state.error_log = "dry_run_would_push"
        else:
            state.sync_status = "Error"
            detail = entry.detail or entry.action
            state.error_log = detail
            if state.enrich_warnings:
                state.error_log = f"{detail}; enrich: {', '.join(state.enrich_warnings)}"


def _refresh_generated_names(session, states: dict[str, CanaryProductState]) -> None:
    for state in states.values():
        if state.product_id is None:
            continue
        product = session.get(Product, state.product_id)
        if product is None:
            continue
        preview, _resolution = generate_preview_for_product(session, product)
        state.generated_name = (product.generated_name or "").strip()
        if not state.generated_name and preview is not None:
            state.generated_name = (preview.name or "").strip()
        if preview is not None and "brand_skipped" in preview.warnings:
            if "brand_skipped" not in state.enrich_warnings:
                state.enrich_warnings.append("brand_skipped")


def render_report(states: dict[str, CanaryProductState]) -> None:
    table = Table(title="Canary E2E Report", show_lines=True)
    table.add_column("Код (default_code)", style="cyan", no_wrap=True)
    table.add_column("Оригинальное имя (Odoo)", overflow="fold")
    table.add_column("Новое сгенерированное имя", overflow="fold")
    table.add_column("Статус отправки", justify="center")
    table.add_column("Лог ошибки (если есть)", overflow="fold", style="red")

    for code in TARGET_CODES:
        state = states.get(code.strip())
        if state is None:
            continue
        status_style = "green" if state.sync_status == "Success" else "red"
        table.add_row(
            state.default_code,
            state.original_odoo_name or "—",
            state.generated_name or "—",
            f"[{status_style}]{state.sync_status}[/{status_style}]",
            state.error_log or "",
        )

    console = Console()
    console.print(table)


def main() -> int:
    console = Console()
    target_codes = [code.strip() for code in TARGET_CODES if code.strip()]
    if not target_codes:
        console.print("[red]ERROR:[/red] TARGET_CODES is empty.")
        return 1

    jsonl_path = DEFAULT_JSONL.resolve()
    if not jsonl_path.is_file():
        console.print(f"[red]ERROR:[/red] JSONL not found: {jsonl_path}")
        return 1

    legacy_db.init_db()
    apply_schema_patches(engine)

    states = {code: CanaryProductState(default_code=code) for code in target_codes}

    try:
        client = OdooClient()
    except OdooClientError as exc:
        console.print(f"[red]ERROR:[/red] Odoo client: {exc}")
        return 1

    ok, message = client.test_connection()
    if not ok:
        console.print(f"[red]ERROR:[/red] Odoo connection failed: {message}")
        return 1
    console.print(f"[green]Connected[/green] to Odoo as: {message}")

    db = SessionLocal()
    try:
        console.print("[bold]Step 1/3[/bold] Extract from Odoo → local DB …")
        extract_target_products(db, client, target_codes, states)

        console.print("[bold]Step 2/3[/bold] Transform via JSONL enrichment …")
        stats = enrich_target_products(db, jsonl_path, target_codes, states)
        _refresh_generated_names(db, states)
        console.print(
            f"  JSONL rows scanned (filtered): {stats.jsonl_rows}, "
            f"matched/applied: {stats.matched_rows}/{stats.applied}, "
            f"errors: {stats.generation_errors}",
        )

        console.print("[bold]Step 3/3[/bold] Load to Odoo (force_apply, live write) …")
        load_target_products(db, client, states, force_apply=True)
        _refresh_generated_names(db, states)
    except OdooClientError as exc:
        console.print(f"[red]ERROR:[/red] Canary pipeline failed: {exc}")
        return 1
    except Exception as exc:
        console.print(f"[red]ERROR:[/red] Unexpected failure: {exc}")
        return 1
    finally:
        db.close()

    render_report(states)
    failed = sum(1 for state in states.values() if state.sync_status != "Success")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
