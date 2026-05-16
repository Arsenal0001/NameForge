"""
Product preview and MoySklad sync orchestration (PROJECT_CONTEXT ops 4–5, 8–9).

Centralizes rules so Streamlit pages stay thin. Preview artifacts remain ephemeral
in session state; this module only computes values and performs DB/API side effects
for approve when not in dry-run.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .db import get_conn
from .fitment_repo import FitmentRow, delete_all_fitment, get_fitment, save_fitment
from .hash_utils import compute_source_hash
from .moysklad_client import MoySkladAPIError, MoySkladAuthError, MoySkladClient
from .name_generator import GeneratedName, generate_name
from .template_engine import load_active_template

logger = logging.getLogger(__name__)

_LOAD_PRODUCT_SQL = """
    SELECT
        id,
        ms_product_id,
        external_code,
        article,
        brand,
        part_type,
        applicability_type,
        side_axis,
        cross_numbers,
        supplier_raw_name,
        primary_make,
        primary_model,
        primary_body,
        year_from,
        year_to,
        engine,
        fitment_summary,
        template_key,
        template_version,
        generation_status,
        name_locked,
        generated_name,
        synced_at,
        error_message,
        source_hash,
        product_folder,
        created_at,
        updated_at
    FROM products
    WHERE id = ?
"""


def load_product_for_workflow(product_id: int) -> dict[str, Any] | None:
    """Full product row for preview/sync (matches sync page needs)."""
    with get_conn() as conn:
        cur = conn.execute(_LOAD_PRODUCT_SQL, (product_id,))
        desc = cur.description
        row = cur.fetchone()
    if row is None or desc is None:
        return None
    cols = [d[0] for d in desc]
    return dict(zip(cols, row, strict=True))


def fitment_dicts_for_product(product_id: int) -> list[dict[str, Any]]:
    return [r.model_dump() for r in get_fitment(product_id)]


def is_workflow_frozen(product: dict[str, Any]) -> bool:
    """Locked by flag or status: preview allowed, auto status change skipped."""
    if int(product.get("name_locked") or 0) == 1:
        return True
    return str(product.get("generation_status") or "") == "locked"


def unlock_name_next_status(source_hash: str | None) -> str:
    """PROJECT_CONTEXT op 7: after unlock_name — review if hash confirmed, else new."""
    return "review" if str(source_hash or "").strip() else "new"


def run_generate_name(
    product: dict[str, Any],
    fitments: list[dict[str, Any]],
) -> tuple[GeneratedName, str]:
    """
    Load active template, run name generator and source hash.
    For missing template, returns status=error GeneratedName and empty hash.
    """
    pattern = load_active_template(
        str(product.get("template_key") or ""),
        str(product.get("applicability_type") or ""),
        part_type=str(product.get("part_type") or "") or None,
    )
    if not pattern:
        empty = GeneratedName(name="", description="", status="error")
        return empty, ""
    gen = generate_name(product, fitments, pattern)
    ch = compute_source_hash(product, fitments)
    return gen, ch


def next_generation_status_after_preview(
    gen: GeneratedName,
    candidate_hash: str,
    source_hash: str,
    *,
    frozen: bool,
) -> str | None:
    """
    DB ``generation_status`` after a preview run (template existed).
    None means leave status unchanged.
    """
    if frozen:
        return None
    if gen.status == "error":
        return "error"
    if gen.status == "review":
        return "review"
    if candidate_hash != str(source_hash or ""):
        return "review"
    return None


@lru_cache(maxsize=1)
def load_nf_attr_map() -> dict[str, Any]:
    """Attribute registry from ``config/attr_map.json`` (same as legacy sync page)."""
    path = Path(__file__).resolve().parent.parent / "config" / "attr_map.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_SKIP_BRAND_DIRECTORY: frozenset[str] = frozenset(
    ("non", "unknown", "?", "н/а", "n/a"),
)


def _brand_requires_ms_directory_match(brand: str | None) -> bool:
    """Non-empty brand other than NON/Unknown/? must resolve in MoySklad «Бренд» directory before PUT."""
    b = str(brand or "").strip()
    if not b:
        return False
    return b.casefold() not in _SKIP_BRAND_DIRECTORY


def build_ms_patch_payload_nf(
    preview_name: str,
    candidate_hash: str,
    preview_description: str = "",
    *,
    attr_entries: dict[str, Any] | None = None,
    product_folder: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """MoySklad PUT body: name, description, NF custom attributes (approved snapshot)."""
    reg = attr_entries if attr_entries is not None else load_nf_attr_map()
    now_iso = datetime.now(timezone.utc).isoformat()
    attributes: list[dict[str, Any]] = [
        {"id": reg["Статус NF"]["id"], "value": "approved"},
        {"id": reg["Хэш NF"]["id"], "value": candidate_hash},
        {"id": reg["Сгенерированное имя NF"]["id"], "value": preview_name},
        {"id": reg["Синхронизировано NF"]["id"], "value": now_iso},
    ]
    payload: dict[str, Any] = {
        "name": preview_name,
        "description": preview_description,
        "attributes": attributes,
    }
    if product_folder:
        payload["productFolder"] = product_folder
    return payload


def is_moysklad_rate_limit_error(exc: BaseException) -> bool:
    """True when MoySklad client failed after HTTP 429 (callers may retry with backoff)."""
    if not isinstance(exc, MoySkladAPIError):
        return False
    t = str(exc).lower()
    return "429" in t or "rate limit" in t


def approve_and_sync_execute(
    client: MoySkladClient | None,
    product: dict[str, Any] | None,
    preview_name: str,
    candidate_hash: str,
    preview_description: str = "",
    *,
    dry_run: bool,
    attr_entries: dict[str, Any] | None = None,
    directory_cache: Any | None = None,
    re_raise_rate_limit: bool = False,
) -> tuple[str, str | None]:
    """
    Validate, optionally PUT MoySklad, update local DB on success/failure.

    Returns ``(code, detail)`` where code is one of:
    ``ok``, ``skipped``, ``error``, ``locked`` — detail clarifies (e.g. ``dry_run``,
    ``no_change``, ``not_found``).
    """
    if not product:
        return "error", "not_found"

    product_id = int(product["id"])

    if int(product.get("name_locked") or 0) == 1:
        return "locked", "name_locked"

    if str(product.get("generation_status") or "") == "locked":
        return "locked", "status_locked"

    src = str(product.get("source_hash") or "")
    if candidate_hash == src:
        return "skipped", "no_change"

    ms_id = str(product.get("ms_product_id") or "").strip()
    if not ms_id:
        return "error", "no_ms_id"

    if not isinstance(client, MoySkladClient):
        return "error", "no_client"

    if dry_run or client.dry_run:
        return "skipped", "dry_run"

    from src.smart_extractor import get_target_folder

    stored = str(product.get("product_folder") or "").strip()
    folder_path = stored or get_target_folder(str(product.get("part_type") or ""))

    brand_raw = str(product.get("brand") or "").strip()
    if _brand_requires_ms_directory_match(brand_raw):
        resolve = getattr(directory_cache, "resolve_brand", None)
        if not callable(resolve) or resolve(brand_raw) is None:
            logger.warning(
                "approve_and_sync_execute: product_id=%s brand=%r not resolvable in MS «Бренд» directory — aborting PUT",
                product_id,
                brand_raw,
            )
            msg = f"Brand not found in MS Directory: {brand_raw}"
            with get_conn() as conn:
                conn.execute(
                    """
                    UPDATE products
                    SET generation_status = ?,
                        error_message = ?
                    WHERE id = ?
                    """,
                    ("review", msg, product_id),
                )
            return "error", "brand_not_in_directory"

    folder_payload: dict[str, Any] | None = None
    if folder_path:
        folder_payload = client.ensure_productfolder(folder_path)
        if not folder_payload:
            logger.warning(
                "approve_and_sync_execute: product_id=%s — productFolder path not found/created in MS, "
                "PUT without productFolder: %r",
                product_id,
                folder_path,
            )


    payload = build_ms_patch_payload_nf(
        preview_name,
        candidate_hash,
        preview_description,
        attr_entries=attr_entries,
        product_folder=folder_payload,
    )

    try:
        resp = client.update_product(
            ms_id,
            payload,
            directory_cache=directory_cache,
            brand=brand_raw,
        )
        if resp.get("dry_run"):
            with get_conn() as conn:
                conn.execute(
                    """
                    UPDATE products
                    SET generation_status = ?,
                        error_message = ?
                    WHERE id = ?
                    """,
                    ("error", "client_dry_run", product_id),
                )
            return "error", "client_dry_run"
    except (MoySkladAPIError, MoySkladAuthError, OSError, ValueError) as exc:
        if re_raise_rate_limit and is_moysklad_rate_limit_error(exc):
            raise
        msg = str(exc)[:4000]
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE products
                SET generation_status = ?,
                    error_message = ?
                WHERE id = ?
                """,
                ("error", msg, product_id),
            )
        return "error", str(exc)

    now_iso = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE products
            SET generation_status = 'approved',
                source_hash = ?,
                generated_name = ?,
                synced_at = ?,
                error_message = NULL
            WHERE id = ? AND name_locked = 0
            """,
            (candidate_hash, preview_name, now_iso, product_id),
        )

    return "ok", None


def _attr_registry_to_id_key(attr_map: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for _label, entry in attr_map.items():
        if isinstance(entry, dict):
            aid = str(entry.get("id") or "").strip()
            key = str(entry.get("key") or "").strip()
            if aid and key:
                out[aid] = key
    return out


def _extract_attrs_ms(ms_product: dict[str, Any], id_to_key: dict[str, str]) -> dict[str, Any]:
    """Same attribute extraction as ``scripts/import_from_ms.extract_attrs`` (inline copy)."""
    result: dict[str, Any] = {}
    for attr in ms_product.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        attr_id = str(attr.get("id") or "")
        key = id_to_key.get(attr_id)
        if not key:
            continue
        val = attr.get("value")
        if isinstance(val, dict):
            result[key] = str(val.get("name") or "")
        elif isinstance(val, bool):
            result[key] = 1 if val else 0
        elif val is None:
            result[key] = ""
        elif isinstance(val, (int, float)) and key in ("year_from", "year_to"):
            result[key] = int(val)
        elif isinstance(val, (int, float)) and key == "name_locked":
            result[key] = 1 if int(val) else 0
        else:
            result[key] = str(val)
    return result


def _safe_int_year(v: Any) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _norm_applicability(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in ("universal", "универсальный"):
        return "universal"
    return "fitment"


def refresh_product_from_ms(
    ms_product_id: str,
    client: MoySkladClient,
    attr_map: dict[str, Any],
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """
    Pull fresh product data from MoySklad, update local DB.
    Returns updated product dict or None on failure.
    Guards: name_locked=1 -> skip update, return current local row.
    Uses extract_attrs pattern from import_from_ms.py (copy, not import).
    Updates: brand, part_type, primary_make/model/body (from MS make/model/body attrs),
             side_axis, engine, year_from, year_to, applicability_type, source_hash.
    Never updates: name_locked, generated_name, synced_at, error_message.
    """
    cur = conn.execute("SELECT * FROM products WHERE ms_product_id = ?", (ms_product_id,))
    row = cur.fetchone()
    if row is None:
        return None
    desc = cur.description
    if desc is None:
        return None
    cols = [d[0] for d in desc]
    local = dict(zip(cols, row, strict=True))

    if int(local.get("name_locked") or 0) == 1:
        return local

    remote = client.get_product(ms_product_id)
    if not remote:
        return None

    id_to_key = _attr_registry_to_id_key(attr_map)
    attrs = _extract_attrs_ms(remote, id_to_key)

    article = str(remote.get("article") or "")
    name = str(remote.get("name") or "")
    brand = str(attrs.get("brand") or "").strip()
    part_type = str(attrs.get("part_type") or "").strip()
    make = str(attrs.get("make") or "").strip()
    model = str(attrs.get("model") or "").strip()
    body = str(attrs.get("body") or "").strip()
    side = str(attrs.get("side") or "").strip()
    engine = str(attrs.get("engine") or "").strip()
    year_from = _safe_int_year(attrs.get("year_from"))
    year_to = _safe_int_year(attrs.get("year_to"))
    app_type = _norm_applicability(str(attrs.get("applicability_type") or "fitment"))

    pid = int(local["id"])

    merged = dict(local)
    merged["article"] = article
    merged["brand"] = brand
    merged["part_type"] = part_type
    merged["applicability_type"] = app_type
    merged["side_axis"] = side or None
    merged["primary_make"] = make or None
    merged["primary_model"] = model or None
    merged["primary_body"] = body or None
    merged["year_from"] = year_from if year_from else None
    merged["year_to"] = year_to if year_to else None
    merged["engine"] = engine or None
    merged["supplier_raw_name"] = name or None

    if app_type == "universal":
        delete_all_fitment(pid)
        fit_dicts: list[dict[str, Any]] = []
    elif make and model:
        save_fitment(
            pid,
            [
                FitmentRow(
                    product_id=pid,
                    make=make,
                    model=model,
                    body=body or None,
                    year_from=year_from if year_from else None,
                    year_to=year_to,
                    engine=engine or None,
                    sort_order=0,
                )
            ],
        )
        fit_dicts = fitment_dicts_for_product(pid)
    else:
        delete_all_fitment(pid)
        fit_dicts = []

    new_hash = compute_source_hash(merged, fit_dicts)

    conn.execute(
        """
        UPDATE products
        SET article = ?,
            brand = ?,
            part_type = ?,
            applicability_type = ?,
            side_axis = ?,
            primary_make = ?,
            primary_model = ?,
            primary_body = ?,
            year_from = ?,
            year_to = ?,
            engine = ?,
            supplier_raw_name = ?,
            source_hash = ?
        WHERE ms_product_id = ? AND name_locked = 0
        """,
        (
            article,
            brand,
            part_type,
            app_type,
            side or None,
            make or None,
            model or None,
            body or None,
            year_from if year_from else None,
            year_to if year_to else None,
            engine or None,
            name or None,
            new_hash,
            ms_product_id,
        ),
    )

    reloaded = load_product_for_workflow(pid)
    return reloaded


def batch_generate_previews(
    product_ids: list[str],
    conn: sqlite3.Connection,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, GeneratedName | None]:
    """
    Generate preview names for multiple products.
    For each product_id (local SQLite id):
      - Load product + fitment rows
      - Pick first active template matching applicability_type
      - Call generate_name()
      - On hash change: set ``generation_status`` to ``review`` and persist ``generated_name``
        (``source_hash`` is not overwritten here — see queue sync idempotency).
    Returns {product_id: GeneratedName | None}
    Max 5 product ids per call — raise ValueError if len > 5.
    progress_callback(current, total) for st.progress() integration.
    """
    if len(product_ids) > 5:
        raise ValueError("batch_generate_previews: at most 5 product ids per run")

    total = len(product_ids)
    out: dict[str, GeneratedName | None] = {}

    for i, pid_raw in enumerate(product_ids):
        if progress_callback is not None and total:
            progress_callback(i + 1, total)

        try:
            pid = int(str(pid_raw).strip())
        except (TypeError, ValueError):
            out[str(pid_raw)] = None
            continue

        product = load_product_for_workflow(pid)
        if not product:
            out[str(pid)] = None
            continue

        frozen = is_workflow_frozen(product)
        ap = str(product.get("applicability_type") or "universal")
        fitment_rows = fitment_dicts_for_product(pid)
        pattern = load_active_template(
            str(product.get("template_key") or ""),
            ap,
            part_type=str(product.get("part_type") or "") or None,
        )

        if not pattern:
            gen = GeneratedName(name="", description="", status="error")
            out[str(pid)] = gen
            if not frozen:
                conn.execute(
                    """
                    UPDATE products
                    SET generation_status = ?,
                        generated_name = NULL,
                        error_message = ?
                    WHERE id = ?
                    """,
                    ("error", "no_active_template", pid),
                )
            continue

        gen = generate_name(product, fitment_rows, pattern)
        chash = compute_source_hash(product, fitment_rows)
        out[str(pid)] = gen

        if frozen:
            continue

        src = str(product.get("source_hash") or "")
        new_status = next_generation_status_after_preview(
            gen,
            chash,
            src,
            frozen=False,
        )
        if new_status is not None:
            if new_status == "review":
                conn.execute(
                    """
                    UPDATE products
                    SET generation_status = ?,
                        generated_name = ?,
                        error_message = NULL
                    WHERE id = ?
                    """,
                    (new_status, gen.name, pid),
                )
            elif new_status == "error":
                conn.execute(
                    """
                    UPDATE products
                    SET generation_status = ?,
                        generated_name = ?,
                        error_message = ?
                    WHERE id = ?
                    """,
                    (
                        new_status,
                        gen.name or None,
                        "generation_error",
                        pid,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE products SET generation_status = ? WHERE id = ?",
                    (new_status, pid),
                )
        elif gen.status == "generated":
            conn.execute(
                """
                UPDATE products
                SET generated_name = ?,
                    error_message = NULL
                WHERE id = ?
                """,
                (gen.name, pid),
            )

    return out
