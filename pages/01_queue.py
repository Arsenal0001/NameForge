"""Queue page: filters, table, open card, batch preview and review sync."""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import streamlit as st

from src.db import APPLICABILITY_TYPES, GENERATION_STATUSES, get_conn
from src.fitment_repo import get_fitment
from src.hash_utils import compute_source_hash
from src.moysklad_client import MoySkladClient
from src.name_generator import generate_name
from src.product_workflow import (
    approve_and_sync_execute,
    load_product_for_workflow,
    next_generation_status_after_preview,
)
from src.template_engine import load_active_template

_LIST_SQL = """
    SELECT id, article, brand, part_type, external_code,
           applicability_type, generation_status,
           name_locked, primary_make, primary_model,
           fitment_summary
    FROM products
    WHERE generation_status IN ({status_ph})
      AND applicability_type IN ({type_ph})
      AND ({search_sql})
    ORDER BY generation_status, brand, article
"""

_LOAD_PRODUCT_SQL = """
    SELECT id, ms_product_id, external_code, article, brand, part_type,
           applicability_type, side_axis, cross_numbers,
           primary_make, primary_model, primary_body,
           year_from, year_to, engine,
           template_key, template_version, source_hash,
           generation_status, name_locked
    FROM products
    WHERE id = ?
"""


def _placeholders(n: int) -> str:
    return ", ".join("?" * n)


def _fetch_queue_rows(
    statuses: list[str],
    appl_types: list[str],
    search: str,
) -> list[dict[str, Any]]:
    if not statuses or not appl_types:
        return []

    status_ph = _placeholders(len(statuses))
    type_ph = _placeholders(len(appl_types))
    search = (search or "").strip()
    if search:
        search_sql = "(article LIKE ? OR brand LIKE ? OR external_code LIKE ?)"
        needle = f"%{search}%"
        search_args = (needle, needle, needle)
    else:
        search_sql = "1 = 1"
        search_args = ()

    sql = _LIST_SQL.format(status_ph=status_ph, type_ph=type_ph, search_sql=search_sql)
    params: tuple[Any, ...] = (*statuses, *appl_types, *search_args)

    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        rows = cur.fetchall()

    return [dict(r) for r in rows]


def _load_product_row(product_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(_LOAD_PRODUCT_SQL, (product_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def _fitment_rows_as_dicts(product_id: int) -> list[dict[str, Any]]:
    return [r.model_dump() for r in get_fitment(product_id)]


def _truncate(s: str | None, max_len: int) -> str:
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _is_queue_row_frozen(r: dict[str, Any]) -> bool:
    """Locked by flag or status: preview allowed, DB status must not auto-change (PROJECT_CONTEXT)."""
    if int(r.get("name_locked") or 0) == 1:
        return True
    return str(r.get("generation_status") or "") == "locked"


def _run_batch_preview(rows: list[dict[str, Any]]) -> int:
    """First 50 from ``rows``; preview always stored; status updates only if not frozen."""
    st.session_state.setdefault("preview", {})

    first = rows[:5]
    if not first:
        return 0

    bar = st.progress(0, text="Пересчёт preview…")
    done = 0
    n = len(first)

    for i, r in enumerate(first):
        pid = int(r["id"])
        frozen = _is_queue_row_frozen(r)
        product = _load_product_row(pid)
        if not product:
            done += 1
            bar.progress((i + 1) / n, text=f"Обработано {i + 1}/{n}")
            continue

        fitment_dicts = _fitment_rows_as_dicts(pid)
        pattern = load_active_template(
            str(product["template_key"]),
            str(product["applicability_type"]),
            part_type=str(product.get("part_type") or "") or None,
        )

        if not pattern:
            st.session_state["preview"][pid] = {
                "preview_name": "",
                "preview_description": "",
                "candidate_hash": "",
            }
            if not frozen:
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE products SET generation_status = ? WHERE id = ?",
                        ("error", pid),
                    )
            done += 1
            bar.progress((i + 1) / n, text=f"Обработано {i + 1}/{n}")
            continue

        gen = generate_name(product, fitment_dicts, pattern)
        candidate_hash = compute_source_hash(product, fitment_dicts)

        st.session_state["preview"][pid] = {
            "preview_name": gen.name,
            "preview_description": gen.description,
            "candidate_hash": candidate_hash,
        }

        if frozen:
            done += 1
            bar.progress((i + 1) / n, text=f"Обработано {i + 1}/{n}")
            continue

        source_hash = str(product.get("source_hash") or "")
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
                    (new_status, pid),
                )

        done += 1
        bar.progress((i + 1) / n, text=f"Обработано {i + 1}/{n}")

    bar.empty()
    return done


def _run_batch_sync_review() -> tuple[int, int, str | None]:
    """
    Up to 50 products: local status ``review`` and preview present.
    Returns (ok_count, err_count, first_error_message).
    """
    if st.session_state.get("dry_run", True):
        return 0, 0, "DRY RUN: запись в МойСклад отключена"

    st.session_state.setdefault("preview", {})
    preview: dict[int, Any] = st.session_state["preview"]

    candidates: list[tuple[int, str, str]] = []
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        for pid_raw, pdata in list(preview.items()):
            try:
                pid = int(pid_raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(pdata, dict):
                continue
            if not pdata.get("preview_name") and not pdata.get("preview_description"):
                continue
            row = conn.execute(
                """
                SELECT id, generation_status, ms_product_id, name_locked, source_hash, brand
                FROM products WHERE id = ?
                """,
                (pid,),
            ).fetchone()
            if not row:
                continue
            if str(row["generation_status"]) != "review":
                continue
            if int(row["name_locked"] or 0) == 1:
                continue
            cand_hash = str(pdata.get("candidate_hash") or "")
            src_hash = str(row["source_hash"] or "")
            if cand_hash == src_hash:
                continue
            candidates.append((pid, str(row["ms_product_id"]), str(row["brand"] or "")))

    candidates.sort(key=lambda x: x[0])
    candidates = candidates[:5]

    if not candidates:
        return (
            0,
            0,
            "Нет товаров для отправки: статус review, есть preview в сессии, "
            "товар не заблокирован (name_locked), candidate_hash отличается от source_hash",
        )

    client: MoySkladClient = st.session_state["ms_client"]
    if client.dry_run:
        return 0, 0, "Клиент МойСклад в режиме DRY RUN — запись отключена"

    ok = 0
    err = 0
    first_err: str | None = None

    bar = st.progress(0, text="Синхронизация с МойСклад…")
    n = len(candidates)

    dc = st.session_state.get("directory_cache")

    for i, (pid, _ms_product_id, _brand_str) in enumerate(candidates):
        pdata = preview.get(pid) or {}
        name = str(pdata.get("preview_name") or "")
        description = str(pdata.get("preview_description") or "")
        candidate_hash = str(pdata.get("candidate_hash") or "")

        product = load_product_for_workflow(pid)
        if not product:
            err += 1
            if first_err is None:
                first_err = "not_found"
            bar.progress((i + 1) / n, text=f"Отправлено {i + 1}/{n}")
            if i < n - 1:
                time.sleep(0.1)
            continue

        code, detail = approve_and_sync_execute(
            client,
            product,
            name,
            candidate_hash,
            description,
            dry_run=False,
            directory_cache=dc,
        )

        if code == "ok":
            preview.pop(pid, None)
            ok += 1
        else:
            err += 1
            if first_err is None:
                first_err = detail or code or "error"

        bar.progress((i + 1) / n, text=f"Отправлено {i + 1}/{n}")
        if i < n - 1:
            time.sleep(0.1)

    bar.empty()
    return ok, err, first_err


st.title("Очередь")
tab_main, tab_errors = st.tabs(["Очередь", "⚠️ Ошибки"])

with tab_main:
    c1, c2, c3 = st.columns(3)
    with c1:
        sel_status = st.multiselect(
            "Статус",
            options=list(GENERATION_STATUSES),
            default=["new", "review", "error"],
        )
    with c2:
        sel_type = st.multiselect(
            "Тип",
            options=list(APPLICABILITY_TYPES),
            default=["fitment", "universal"],
        )
    with c3:
        search = st.text_input(
            "Поиск",
            placeholder="артикул / бренд / внешний код",
            label_visibility="visible",
        )

    only_missing_article = st.checkbox(
        "⚠️ Без артикула",
        value=False,
        key="queue_filter_missing_article",
        help="Показать только товары с пустым артикулом.",
    )

    if not sel_status or not sel_type:
        st.warning("Выберите хотя бы один статус и один тип применимости.")
    queue_rows = _fetch_queue_rows(list(sel_status), list(sel_type), search)

    if only_missing_article:
        queue_rows = [
            r for r in queue_rows if not str(r.get("article") or "").strip()
        ]

    st.caption(f"Найдено: {len(queue_rows)} товаров")

    display: list[dict[str, Any]] = []
    for r in queue_rows:
        locked = int(r.get("name_locked") or 0) == 1
        display.append(
            {
                "article": r.get("article", ""),
                "external_code": r.get("external_code", ""),
                "brand": r.get("brand", ""),
                "part_type": r.get("part_type", ""),
                "applicability_type": r.get("applicability_type", ""),
                "generation_status": r.get("generation_status", ""),
                "🔒": "🔒" if locked else "",
                "primary_make": r.get("primary_make") or "",
                "fitment_summary": _truncate(r.get("fitment_summary"), 60),
            }
        )

    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
    )

    ids = [int(r["id"]) for r in queue_rows]
    labels = [f"{r.get('article', '')} — {r.get('brand', '')}" for r in queue_rows]

    col1, col2 = st.columns([4, 1])
    with col1:
        if ids:
            pick_idx = st.selectbox(
                "Открыть карточку",
                options=list(range(len(ids))),
                format_func=lambda i: labels[i],
                key="queue_open_card",
            )
        else:
            pick_idx = None
            st.selectbox(
                "Открыть карточку",
                options=["— нет товаров —"],
                disabled=True,
                key="queue_open_card_empty",
            )

    with col2:
        st.write("")  # align with selectbox
        st.write("")
        if ids and st.button("Открыть →", key="queue_open_card_btn"):
            assert pick_idx is not None
            st.session_state["selected_product_id"] = ids[pick_idx]
            st.switch_page("pages/02_card.py")

    with st.expander("⚡ Пакетные операции"):
        st.caption(
            "Не более **5** позиций за запуск (первые в текущей выборке). "
            "Между запросами в МойСклад — пауза **0,1 с**. "
            "Для заблокированных товаров preview считается, но статус в БД не меняется."
        )
        if st.button("🔄 Пересчитать preview (5)", key="batch_preview"):
            n = _run_batch_preview(queue_rows)
            if n:
                st.success(f"Пересчитано: {n} товаров")
            else:
                st.info("Нет строк в выборке или список пуст — нечего пересчитывать.")

        sync_disabled = bool(st.session_state.get("dry_run", True))
        if st.button(
            "✅ Синхронизировать review (5)",
            disabled=sync_disabled,
            key="batch_sync_review",
        ):
            ok, bad, msg = _run_batch_sync_review()
            if bad == 0 and ok > 0:
                st.success(f"Синхронизировано: {ok} товаров")
            elif ok == 0 and bad == 0:
                st.error(msg or "Нечего синхронизировать")
            elif bad:
                st.error(
                    f"Ошибок: {bad}, успешно: {ok}. "
                    f"{msg or ''}"
                )
            elif ok:
                st.success(f"Синхронизировано: {ok} товаров")

with tab_errors:
    st.caption(
        "Товары со статусом «error». Сообщение из последней неудачной синхронизации — в колонке error_message."
    )
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        err_rows = conn.execute(
            """
            SELECT id, article, brand, part_type, supplier_raw_name, generation_status,
                   error_message
            FROM products
            WHERE generation_status = 'error'
            ORDER BY id
            """
        ).fetchall()
    err_list = [dict(r) for r in err_rows]
    if not err_list:
        st.info("Нет товаров со статусом error.")
    else:
        st.dataframe(
            [
                {
                    "id": r["id"],
                    "article": r.get("article") or "",
                    "brand": r.get("brand") or "",
                    "part_type": r.get("part_type") or "",
                    "supplier_raw_name": _truncate(r.get("supplier_raw_name"), 80),
                    "error_message": _truncate(r.get("error_message"), 120) or "—",
                }
                for r in err_list
            ],
            use_container_width=True,
            hide_index=True,
        )
        for r in err_list:
            pid = int(r["id"])
            label = f"{pid} — {r.get('article', '')}"
            if st.button("🔄 Сбросить в new", key=f"queue_err_reset_{pid}"):
                with get_conn() as conn:
                    conn.execute(
                        """
                        UPDATE products
                        SET generation_status = 'new',
                            error_message = NULL
                        WHERE id = ?
                        """,
                        (pid,),
                    )
                st.rerun()
                st.stop()
