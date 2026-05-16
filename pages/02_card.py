"""Single product card: attributes, fitment editor, preview and sync."""

from __future__ import annotations

import sqlite3
from typing import Any

import pandas as pd
import streamlit as st

from src.db import get_conn
from src.fitment_repo import FitmentRow, get_fitment, save_fitment
from src.hash_utils import compute_source_hash
from src.moysklad_client import MoySkladAPIError, MoySkladAuthError, MoySkladClient
from src.name_generator import generate_name
from src.product_workflow import (
    approve_and_sync_execute,
    is_workflow_frozen,
    load_nf_attr_map,
    next_generation_status_after_preview,
    refresh_product_from_ms,
    unlock_name_next_status,
)
from src.template_engine import list_templates, load_active_template


def _enrich_product_name(product: dict[str, Any]) -> None:
    """Set ``product["name"]`` from MoySklad when missing in SQLite."""
    if product.get("name"):
        return
    client = st.session_state.get("ms_client")
    ms_id = product.get("ms_product_id")
    if not client or not ms_id or not st.session_state.get("_ms_token_configured"):
        product.setdefault("name", "")
        return
    try:
        remote = client.get_product(str(ms_id))
        if remote:
            product["name"] = str(remote.get("name") or "")
        else:
            product.setdefault("name", "")
    except (MoySkladAPIError, MoySkladAuthError, OSError, ValueError):
        product.setdefault("name", "")


def _load_product(product_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = cur.fetchone()
    if not row:
        return None
    product = dict(row)
    _enrich_product_name(product)
    return product


def _template_keys_for_applicability(applicability_type: str) -> list[str]:
    rows = list_templates()
    keys = sorted(
        {str(r["template_key"]) for r in rows if str(r.get("applicability_type")) == applicability_type}
    )
    if not keys:
        keys = sorted({str(r["template_key"]) for r in rows})
    return keys


def _active_template_version(conn: sqlite3.Connection, template_key: str, applicability_type: str) -> str | None:
    row = conn.execute(
        """
        SELECT version
        FROM templates
        WHERE template_key = ?
          AND applicability_type = ?
          AND is_active = 1
        ORDER BY version DESC
        LIMIT 1
        """,
        (template_key, applicability_type),
    ).fetchone()
    return str(row[0]) if row else None


def _fitment_dicts(product_id: int) -> list[dict[str, Any]]:
    return [r.model_dump() for r in get_fitment(product_id)]


def _int_or_none(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    if val == "":
        return None
    if isinstance(val, bool):
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _is_truthy_primary(val: Any) -> bool:
    if val is True:
        return True
    if val in (1, "1"):
        return True
    if isinstance(val, float) and not pd.isna(val) and int(val) == 1:
        return True
    return False


def _fitment_rows_from_dataframe(df: pd.DataFrame, product_id: int) -> list[FitmentRow]:
    rows: list[FitmentRow] = []
    for _, row in df.iterrows():
        make = str(row.get("make") or "").strip()
        model = str(row.get("model") or "").strip()
        if not make and not model:
            continue
        body_raw = row.get("body")
        if body_raw is None or (isinstance(body_raw, float) and pd.isna(body_raw)):
            body = ""
        else:
            body = str(body_raw).strip()
        body_val = body if body else None
        eng_raw = row.get("engine")
        if eng_raw is None or (isinstance(eng_raw, float) and pd.isna(eng_raw)):
            engine = ""
        else:
            engine = str(eng_raw).strip()
        engine_val = engine if engine else None
        rows.append(
            FitmentRow(
                product_id=product_id,
                make=make,
                model=model,
                body=body_val,
                year_from=_int_or_none(row.get("year_from")),
                year_to=_int_or_none(row.get("year_to")),
                engine=engine_val,
                is_primary=1 if _is_truthy_primary(row.get("is_primary")) else 0,
                sort_order=int(_int_or_none(row.get("sort_order")) or 0),
            )
        )
    return rows


def _pin_primary_via_sort_order(rows: list[FitmentRow]) -> None:
    """Ensure the primary-marked row wins default primary resolution (sort_order, id)."""
    primary_idx: int | None = None
    for i, r in enumerate(rows):
        if r.is_primary:
            primary_idx = i
            break
    if primary_idx is None:
        return
    mins = min((r.sort_order for r in rows), default=0)
    rows[primary_idx].sort_order = mins - 1


def _merge_product_from_widgets(base: dict[str, Any]) -> dict[str, Any]:
    p = dict(base)
    p["brand"] = str(st.session_state.get("card_brand", p.get("brand") or ""))
    p["part_type"] = str(st.session_state.get("card_part_type", p.get("part_type") or ""))
    p["applicability_type"] = str(st.session_state.get("card_applicability", p.get("applicability_type") or ""))
    p["side_axis"] = str(st.session_state.get("card_side_axis", p.get("side_axis") or "")) or None
    p["cross_numbers"] = str(st.session_state.get("card_cross_numbers", p.get("cross_numbers") or "")) or None
    p["supplier_raw_name"] = str(st.session_state.get("card_supplier_raw_name", p.get("supplier_raw_name") or "")) or None
    tk = str(st.session_state.get("card_template_key", p.get("template_key") or ""))
    p["template_key"] = tk
    appl = str(p["applicability_type"] or "")
    with get_conn() as conn:
        ver = _active_template_version(conn, tk, appl)
    if ver:
        p["template_version"] = ver
    return p


st.title("Карточка товара")

st.session_state.setdefault("preview", {})

pid_raw = st.session_state.get("selected_product_id")
if pid_raw is None:
    st.info("Выберите товар в Очереди")
    st.stop()

try:
    product_id = int(pid_raw)
except (TypeError, ValueError):
    st.error("Некорректный идентификатор товара")
    st.stop()

product = _load_product(product_id)
if not product:
    st.error("Товар не найден в базе")
    st.stop()

name_locked = int(product.get("name_locked") or 0) == 1
dry_run = bool(st.session_state.get("dry_run", True))
client = st.session_state["ms_client"]

with st.sidebar:
    with get_conn() as conn:
        locked_n = int(
            conn.execute("SELECT COUNT(*) FROM products WHERE name_locked = 1").fetchone()[0]
        )
    st.metric("Заблокировано имён (всего)", locked_n)
    if name_locked:
        if st.button("🔓 Разблокировать", key="card_sidebar_unlock"):
            src = str(product.get("source_hash") or "")
            new_status = unlock_name_next_status(src)
            with get_conn() as conn:
                conn.execute(
                    """
                    UPDATE products
                    SET name_locked = 0,
                        generation_status = ?
                    WHERE id = ?
                    """,
                    (new_status, product_id),
                )
            st.rerun()
            st.stop()

st.subheader("Основное")
col_refresh, _ = st.columns([1, 3])
with col_refresh:
    if st.button("🔄 Обновить из МС", key="card_refresh_from_ms"):
        ms_id = str(product.get("ms_product_id") or "").strip()
        if not ms_id:
            st.error("Нет ms_product_id")
        else:
            cl = st.session_state.get("ms_client")
            if not isinstance(cl, MoySkladClient):
                st.error("Клиент МойСклад недоступен")
            else:
                with get_conn() as conn:
                    refresh_product_from_ms(ms_id, cl, load_nf_attr_map(), conn)
                st.rerun()
                st.stop()
col1, col2 = st.columns(2)

with col1:
    st.text_input(
        "Артикул",
        value=str(product.get("article") or ""),
        disabled=True,
        key="card_article",
    )
    st.text_input("Бренд", value=str(product.get("brand") or ""), key="card_brand")
    st.text_input("Тип детали", value=str(product.get("part_type") or ""), key="card_part_type")
    appl_options = ["fitment", "universal"]
    appl_default = str(product.get("applicability_type") or "fitment")
    appl_index = appl_options.index(appl_default) if appl_default in appl_options else 0
    applicability_type = st.selectbox(
        "Тип применимости",
        options=appl_options,
        index=appl_index,
        key="card_applicability",
    )

with col2:
    st.text_input(
        "Сторона / ось",
        value=str(product.get("side_axis") or ""),
        key="card_side_axis",
        placeholder="опционально",
    )
    st.text_area(
        "Кросс-номера",
        value=str(product.get("cross_numbers") or ""),
        key="card_cross_numbers",
        placeholder="опционально",
    )
    st.text_input(
        "Имя поставщика (сырое)",
        value=str(product.get("supplier_raw_name") or ""),
        key="card_supplier_raw_name",
        placeholder="опционально",
    )
    template_keys = _template_keys_for_applicability(str(applicability_type))
    tk_default = str(product.get("template_key") or "")
    if tk_default in template_keys:
        tk_index = template_keys.index(tk_default)
    else:
        tk_index = 0
    template_key = (
        st.selectbox(
            "Шаблон (ключ)",
            options=template_keys if template_keys else ["—"],
            index=min(tk_index, max(len(template_keys) - 1, 0)) if template_keys else 0,
            key="card_template_key",
            disabled=not template_keys,
        )
        if template_keys
        else "—"
    )

if st.button("💾 Сохранить основное", key="card_save_main"):
    if not template_keys or template_key == "—":
        st.error("Нет шаблонов для выбранного типа применимости")
    else:
        with get_conn() as conn:
            ver = _active_template_version(conn, str(template_key), str(applicability_type))
            if not ver:
                st.error("Нет активной версии шаблона для выбранных ключа и типа")
            else:
                conn.execute(
                    """
                    UPDATE products
                    SET brand = ?,
                        part_type = ?,
                        applicability_type = ?,
                        side_axis = ?,
                        cross_numbers = ?,
                        supplier_raw_name = ?,
                        template_key = ?,
                        template_version = ?
                    WHERE id = ?
                    """,
                    (
                        str(st.session_state.get("card_brand", "")).strip(),
                        str(st.session_state.get("card_part_type", "")).strip(),
                        str(st.session_state.get("card_applicability", "")).strip(),
                        (str(st.session_state.get("card_side_axis", "")).strip() or None),
                        (str(st.session_state.get("card_cross_numbers", "")).strip() or None),
                        (str(st.session_state.get("card_supplier_raw_name", "")).strip() or None),
                        str(template_key),
                        str(ver),
                        product_id,
                    ),
                )
        st.rerun()

if str(applicability_type) == "fitment":
    st.subheader("Применимость (Fitment)")
    fitment_models = get_fitment(product_id)
    _fitment_cols = (
        "make",
        "model",
        "body",
        "year_from",
        "year_to",
        "engine",
        "sort_order",
        "is_primary",
    )
    fitment_records: list[dict[str, Any]] = []
    for m in fitment_models:
        r = m.model_dump()
        row = {c: r.get(c) for c in _fitment_cols}
        row["is_primary"] = bool(int(r.get("is_primary") or 0))
        fitment_records.append(row)

    df = (
        pd.DataFrame(fitment_records)
        if fitment_records
        else pd.DataFrame(columns=list(_fitment_cols))
    )

    edited = st.data_editor(
        df,
        num_rows="dynamic",
        key=f"fitment_editor_{product_id}",
        hide_index=True,
        use_container_width=True,
        column_config={
            "make": st.column_config.TextColumn("make", required=True),
            "model": st.column_config.TextColumn("model", required=True),
            "body": st.column_config.TextColumn("body"),
            "year_from": st.column_config.NumberColumn("year_from", min_value=1970, max_value=2030, step=1),
            "year_to": st.column_config.NumberColumn(
                "year_to",
                min_value=0,
                max_value=2030,
                step=1,
                help="0 = н.в.",
            ),
            "engine": st.column_config.TextColumn("engine"),
            "sort_order": st.column_config.NumberColumn("sort_order", step=1),
            "is_primary": st.column_config.CheckboxColumn("📌 Primary", default=False),
        },
    )
    st.caption(
        "📌 Отметьте одну строку как Primary — она попадёт в наименование"
    )

    if st.button("💾 Сохранить применимость", key="card_save_fitment"):
        try:
            rows = _fitment_rows_from_dataframe(edited, product_id)
            _pin_primary_via_sort_order(rows)
            save_fitment(product_id, rows, None)
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success("Применимость сохранена")
            st.rerun()

st.subheader("Генерация имени")
current_name = str(product.get("name") or "").strip() or "—"
st.caption(f"Текущее: {current_name}")

if st.button("🔍 Сгенерировать preview", key="card_preview_btn"):
    product_reload = _load_product(product_id) or product
    merged = _merge_product_from_widgets(product_reload)
    tk = str(merged.get("template_key") or "")
    appl = str(merged.get("applicability_type") or "")
    pattern = load_active_template(
        tk,
        appl,
        part_type=str(merged.get("part_type") or "") or None,
    )
    fitment_dicts = _fitment_dicts(product_id)

    if not pattern:
        st.session_state["preview"][product_id] = {
            "preview_name": "",
            "preview_description": "",
            "candidate_hash": "",
        }
        with get_conn() as conn:
            conn.execute(
                "UPDATE products SET generation_status = ? WHERE id = ?",
                ("error", product_id),
            )
        st.error("Активный шаблон не найден")
        st.rerun()

    gen = generate_name(merged, fitment_dicts, pattern)
    candidate_hash = compute_source_hash(merged, fitment_dicts)
    st.session_state["preview"][product_id] = {
        "preview_name": gen.name,
        "preview_description": gen.description,
        "candidate_hash": candidate_hash,
    }

    source_hash = str(product_reload.get("source_hash") or "")
    frozen = is_workflow_frozen(product_reload)
    new_status = next_generation_status_after_preview(
        gen,
        candidate_hash,
        source_hash,
        frozen=frozen,
    )

    if new_status is not None:
        with get_conn() as conn:
            conn.execute(
                "UPDATE products SET generation_status = ? WHERE id = ?",
                (new_status, product_id),
            )
    st.rerun()

preview_store: dict[Any, Any] = st.session_state.get("preview") or {}
preview_entry = preview_store.get(product_id) if isinstance(preview_store, dict) else None

if isinstance(preview_entry, dict) and preview_entry:
    preview_name = str(preview_entry.get("preview_name") or "")
    preview_description = str(preview_entry.get("preview_description") or "")
    candidate_hash = str(preview_entry.get("candidate_hash") or "")
    source_hash = str(product.get("source_hash") or "")

    col_new, col_old = st.columns(2)
    with col_new:
        st.success(preview_name or "—")
    with col_old:
        st.caption(current_name)

    st.text_area("Описание", preview_description, disabled=True, key="card_preview_description")

    hash_changed = candidate_hash != source_hash
    if hash_changed:
        st.info("✏️ Изменения есть — требуется синхронизация")
    else:
        st.info("✅ Изменений нет — синхронизация не нужна")

    c1, c2, c3 = st.columns(3)
    with c1:
        confirm_disabled = dry_run or not hash_changed or name_locked
        if st.button(
            "📤 Подтвердить и отправить",
            disabled=confirm_disabled,
            key="card_confirm_sync",
        ):
            if dry_run or client.dry_run:
                st.error("Включён DRY RUN — отправка в МойСклад отключена")
            elif not hash_changed:
                st.warning("Нет изменений для отправки")
            elif name_locked:
                st.warning("Имя заблокировано")
            else:
                code, detail = approve_and_sync_execute(
                    client if isinstance(client, MoySkladClient) else None,
                    product,
                    preview_name,
                    candidate_hash,
                    preview_description,
                    dry_run=bool(dry_run or getattr(client, "dry_run", False)),
                    directory_cache=st.session_state.get("directory_cache"),
                )
                if code == "ok":
                    preview_store.pop(product_id, None)
                    st.session_state["preview"] = preview_store
                    st.rerun()
                elif code == "error":
                    if detail == "not_found":
                        st.error("Товар не найден.")
                    elif detail == "no_ms_id":
                        st.error("Нет ms_product_id.")
                    elif detail == "no_client":
                        st.error("Клиент МойСклад не инициализирован.")
                    elif detail == "client_dry_run":
                        st.error("Клиент в режиме DRY RUN — отправка отменена")
                    else:
                        st.error(f"Ошибка API: {detail}")
                elif code == "locked":
                    if detail == "name_locked":
                        st.error("Имя заблокировано — синхронизация запрещена.")
                    elif detail == "status_locked":
                        st.error("Статус «locked» — синхронизация запрещена.")
                    else:
                        st.error(str(detail or code))
                elif code == "skipped":
                    if detail == "no_change":
                        st.info("Нет изменений для отправки")
                    elif detail == "dry_run":
                        st.error("Включён DRY RUN — отправка в МойСклад отключена")
                    else:
                        st.warning(str(detail or code))
                else:
                    st.warning(str(detail or code))

    with c2:
        if st.button("⏭️ Пропустить", key="card_skip_approve"):
            with get_conn() as conn:
                conn.execute(
                    "UPDATE products SET generation_status = ? WHERE id = ?",
                    ("approved", product_id),
                )
            st.rerun()

    with c3:
        if name_locked:
            if st.button("🔓 Разблокировать", key="card_unlock_name"):
                src = str(product.get("source_hash") or "")
                new_status = unlock_name_next_status(src)
                with get_conn() as conn:
                    conn.execute(
                        """
                        UPDATE products
                        SET name_locked = 0,
                            generation_status = ?
                        WHERE id = ?
                        """,
                        (new_status, product_id),
                    )
                st.rerun()
        else:
            if st.button("🔒 Заблокировать", key="card_lock_name"):
                with get_conn() as conn:
                    conn.execute(
                        """
                        UPDATE products
                        SET name_locked = 1,
                            generation_status = 'locked'
                        WHERE id = ?
                        """,
                        (product_id,),
                    )
                st.rerun()
