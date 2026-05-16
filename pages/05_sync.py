"""
Name generation & MoySklad sync: preview, approve, batch.

Согласовано с DEVELOPMENT_PLAN.md: эфемерный preview в session_state (имя, описание, hash),
переход в review только при смене hash (§6.4), запись в МойСклад с description (§3, риск §10).

Тела запросов собираются только в ``product_workflow.build_ms_patch_payload_nf`` (через
``approve_and_sync_execute`` / ``approve_and_sync``), без ручной сборки на странице.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.db import GENERATION_STATUSES, get_conn
from src.hash_utils import compute_source_hash
from src.moysklad_client import MoySkladClient
from src.name_generator import generate_name
from src.product_workflow import (
    approve_and_sync_execute,
    batch_generate_previews,
    fitment_dicts_for_product,
    is_workflow_frozen,
    load_product_for_workflow,
)
from src.template_engine import list_templates

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LAST_SYNC_LOG = _PROJECT_ROOT / "logs" / "last_sync.log"


def _append_last_sync_log(article: str, product_id: int) -> None:
    """Append one line after a successful MoySklad PUT (resumable progress)."""
    art = (article or "").replace("\n", " ").replace("\r", " ").strip()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] SUCCESS: {art} {product_id}\n"
    _LAST_SYNC_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(_LAST_SYNC_LOG, "a", encoding="utf-8") as f:
        f.write(line)


def _truncate(s: str | None, max_len: int) -> str:
    if not s:
        return ""
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _placeholders(n: int) -> str:
    return ", ".join("?" * n)


def _fetch_queue_rows(
    statuses: list[str],
    brand_filter: str,
    applicability: str,
) -> list[dict[str, Any]]:
    if not statuses:
        return []

    brand_filter = (brand_filter or "").strip()
    ph = _placeholders(len(statuses))
    conds: list[str] = [f"generation_status IN ({ph})"]
    params: list[Any] = list(statuses)

    if brand_filter:
        conds.append("brand LIKE ?")
        params.append(f"%{brand_filter}%")

    if applicability in ("fitment", "universal"):
        conds.append("applicability_type = ?")
        params.append(applicability)

    sql = f"""
        SELECT id, supplier_raw_name, brand, part_type, generation_status, source_hash,
               applicability_type, name_locked
        FROM products
        WHERE {" AND ".join(conds)}
        ORDER BY id
    """
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, tuple(params))
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def _rows_display_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "id",
                "supplier_raw_name",
                "brand",
                "part_type",
                "generation_status",
                "source_hash",
            ]
        )
    data: list[dict[str, Any]] = []
    for r in rows:
        h = str(r.get("source_hash") or "")
        data.append(
            {
                "id": r.get("id"),
                "supplier_raw_name": _truncate(r.get("supplier_raw_name"), 60),
                "brand": r.get("brand") or "",
                "part_type": r.get("part_type") or "",
                "generation_status": r.get("generation_status") or "",
                "source_hash": h[:8] if h else "",
            }
        )
    return pd.DataFrame(data)


def _fitment_dicts(product_id: int) -> list[dict[str, Any]]:
    return fitment_dicts_for_product(product_id)


def _active_templates_for_type(applicability_type: str) -> list[dict[str, Any]]:
    at = str(applicability_type or "")
    return [
        t
        for t in list_templates()
        if int(t.get("is_active") or 0) == 1 and str(t.get("applicability_type") or "") == at
    ]


def _default_template_index(product: dict[str, Any], active_tpls: list[dict[str, Any]]) -> int:
    """Позиция шаблона, совпадающего с template_key/version товара (см. DEVELOPMENT_PLAN §5.1)."""
    tk = str(product.get("template_key") or "")
    tv = str(product.get("template_version") or "")
    for i, t in enumerate(active_tpls):
        if str(t.get("template_key") or "") == tk and str(t.get("version") or "") == tv:
            return i
    return 0


def approve_and_sync(
    product_id: int,
    preview_name: str,
    candidate_hash: str,
    preview_description: str = "",
    *,
    batch: bool = False,
) -> tuple[str, str | None]:
    """
    PUT MoySklad (name, description, NF-attrs) + update local DB.
    Returns (code, detail): ok | skipped | error | locked
    """
    st.session_state.setdefault("preview", {})

    product = load_product_for_workflow(product_id)
    client = st.session_state.get("ms_client")
    dry = bool(st.session_state.get("dry_run", True))

    dc = st.session_state.get("directory_cache")
    code, detail = approve_and_sync_execute(
        client if isinstance(client, MoySkladClient) else None,
        product,
        preview_name,
        candidate_hash,
        preview_description,
        dry_run=dry,
        directory_cache=dc,
    )

    if code == "error":
        if detail == "not_found" and not batch:
            st.error("Товар не найден.")
        elif detail == "no_ms_id" and not batch:
            st.error("Нет ms_product_id.")
        elif detail == "no_client" and not batch:
            st.error("Клиент МойСклад не инициализирован.")
        elif detail == "client_dry_run" and not batch:
            st.error("Клиент в режиме DRY RUN — запись отменена.")
        elif detail not in (
            "not_found",
            "no_ms_id",
            "no_client",
            "client_dry_run",
        ) and not batch:
            st.error(f"Ошибка API: {detail}")
        return code, detail

    if code == "locked":
        if detail == "name_locked" and not batch:
            st.error("Имя заблокировано — синхронизация запрещена.")
        elif detail == "status_locked" and not batch:
            st.error("Статус «locked» — синхронизация запрещена.")
        return code, detail

    if code == "skipped":
        if detail == "no_change" and not batch:
            st.info("Имя не изменилось — запись в МойСклад не требуется.")
        elif detail == "dry_run" and not batch:
            ms_id = str((product or {}).get("ms_product_id") or "").strip()
            st.info(
                f"DRY_RUN: запись в МойСклад не выполняется (product id={product_id}, ms_id={ms_id})"
            )
        return code, detail

    if code == "ok":
        _append_last_sync_log(str((product or {}).get("article") or ""), product_id)

    st.session_state["preview"].pop(product_id, None)
    st.session_state["preview"].pop(str(product_id), None)

    if not batch:
        st.rerun()
        st.stop()
    return "ok", None


st.title("Синхронизация")
st.caption(
    "Полуавтоматический контур: предпросмотр → при необходимости статус "
    "«на проверку» → утверждение → запись в МойСклад (PUT). Черновик имени, описания и hash "
    "в session_state до подтверждения (DEVELOPMENT_PLAN §2–3)."
)

if st.session_state.get("dry_run", True):
    st.sidebar.warning("DRY_RUN активен — запись в МойСклад не выполняется")

with get_conn() as conn:
    _n_review = conn.execute(
        "SELECT COUNT(*) FROM products WHERE generation_status = 'review'"
    ).fetchone()[0]
    _n_review_synced = conn.execute(
        """
        SELECT COUNT(*) FROM products
        WHERE generation_status = 'review'
          AND TRIM(COALESCE(synced_at, '')) != ''
        """
    ).fetchone()[0]

st.subheader("Статистика очереди")
_c1, _c2 = st.columns(2)
with _c1:
    st.metric("Всего в статусе «review»", int(_n_review))
with _c2:
    st.metric(
        "Из них с заполненным synced_at",
        int(_n_review_synced),
        help="Обычно после успешного PUT статус становится «approved»; ненулевое значение здесь — редкий случай.",
    )
st.caption(
    "Успешные PUT с этой страницы дополнительно пишутся в файл "
    "`logs/last_sync.log` относительно корня проекта."
)

# ——— SECTION 1 — queue table
st.subheader("Очередь")
c1, c2, c3 = st.columns(3)
with c1:
    sel_status = st.multiselect(
        "Статус",
        options=list(GENERATION_STATUSES),
        default=["new", "review", "error"],
        key="sync_sel_status",
    )
with c2:
    brand_filter = st.text_input("Бренд", key="sync_brand")
with c3:
    appl_filter = st.selectbox(
        "Тип применимости",
        options=["Все", "fitment", "universal"],
        key="sync_appl",
    )

if not sel_status:
    st.warning("Выберите хотя бы один статус.")
    queue_rows: list[dict[str, Any]] = []
else:
    appl_val = "all" if appl_filter == "Все" else str(appl_filter)
    queue_rows = _fetch_queue_rows(list(sel_status), brand_filter, appl_val)

st.caption(f"Найдено: {len(queue_rows)} товаров")
st.dataframe(
    _rows_display_df(queue_rows),
    use_container_width=True,
    hide_index=True,
)

# ——— SECTION 2 — single product preview
st.subheader("Предпросмотр одного товара")
ids = [int(r["id"]) for r in queue_rows]
labels = [f"{r.get('id')} — {r.get('brand', '')} — {r.get('part_type', '')}" for r in queue_rows]

if not ids:
    st.info("Нет строк в выборке — смените фильтры.")
    pick_id: int | None = None
else:
    pick_id = st.selectbox(
        "Товар (id)",
        options=ids,
        format_func=lambda i: labels[ids.index(i)],
        key="sync_pick_id",
    )
    prod0 = load_product_for_workflow(pick_id) or {}
    selected_appl = str(prod0.get("applicability_type") or "universal")
    active_tpls = _active_templates_for_type(selected_appl)
    selected_tpl: dict[str, Any] | None
    if not active_tpls:
        st.warning("Нет активных шаблонов для этого типа применимости.")
        selected_tpl = None
    else:
        tpl_labels = [
            f"{r.get('template_key', '')} {r.get('version', '')} ({r.get('applicability_type', '')})"
            for r in active_tpls
        ]
        _didx = min(
            _default_template_index(prod0, active_tpls),
            max(0, len(tpl_labels) - 1),
        )
        tpl_idx = st.selectbox(
            "Шаблон",
            options=list(range(len(tpl_labels))),
            format_func=lambda i: tpl_labels[i],
            key=f"sync_tpl_pick_{pick_id}",
            index=_didx,
        )
        selected_tpl = active_tpls[int(tpl_idx)]

    if st.button("▶️ Предпросмотр", key="sync_preview_one"):
        if pick_id is None or not selected_tpl:
            st.error("Выберите товар и шаблон.")
        else:
            product = load_product_for_workflow(pick_id)
            if not product:
                st.error("Товар не найден.")
            else:
                st.session_state.setdefault("preview", {})
                fitment_rows = _fitment_dicts(pick_id)
                pattern = str(selected_tpl.get("name_pattern") or "")
                gen = generate_name(product, fitment_rows, pattern)
                chash = compute_source_hash(product, fitment_rows)
                st.session_state["preview"][pick_id] = {
                    "preview_name": gen.name,
                    "preview_description": gen.description,
                    "candidate_hash": chash,
                }
                src = str(product.get("source_hash") or "")
                # DEVELOPMENT_PLAN §6.4: в review — только если hash изменился и preview успешен
                if not is_workflow_frozen(product) and gen.status == "error":
                    with get_conn() as conn:
                        conn.execute(
                            "UPDATE products SET generation_status = ? WHERE id = ?",
                            ("error", pick_id),
                        )
                elif (
                    not is_workflow_frozen(product)
                    and gen.status == "generated"
                    and chash != src
                ):
                    with get_conn() as conn:
                        conn.execute(
                            "UPDATE products SET generation_status = ? WHERE id = ?",
                            ("review", pick_id),
                        )
                st.rerun()
                st.stop()

    pv = (st.session_state.get("preview") or {}).get(pick_id) or (st.session_state.get("preview") or {}).get(
        str(pick_id)
    )
    if pick_id is not None and isinstance(pv, dict) and (pv.get("preview_name") is not None or pv.get("candidate_hash")):
        preview_name = str(pv.get("preview_name") or "")
        preview_desc = str(pv.get("preview_description") or "")
        candidate_hash = str(pv.get("candidate_hash") or "")
        st.code(preview_name)
        st.caption(f"Hash: {candidate_hash[:8]}…" if len(candidate_hash) >= 8 else f"Hash: {candidate_hash}")
        if preview_desc:
            with st.expander("Описание (текст в МойСклад вместе с именем при синхронизации)"):
                st.text(preview_desc)

        product_row = load_product_for_workflow(pick_id) if pick_id is not None else None
        stored = str((product_row or {}).get("source_hash") or "")
        gstat = str((product_row or {}).get("generation_status") or "")
        if product_row and (
            int(product_row.get("name_locked") or 0) == 1 or gstat == "locked"
        ):
            st.warning("Товар заблокирован (name_locked / locked) — утверждение отключено.")
        elif candidate_hash == stored and stored:
            st.info("Имя не изменилось — запись в МойСклад не требуется")
        else:
            if st.button("✅ Утвердить и синхронизировать", key="sync_approve_one"):
                approve_and_sync(
                    pick_id,
                    preview_name,
                    candidate_hash,
                    preview_desc,
                    batch=False,
                )

# ——— SECTION 3 — batch
with st.expander("📦 Пакетная синхронизация"):
    st.session_state.setdefault("preview", {})
    st.caption(
        "До **50** товаров за запуск; генерация идёт чанками по 5 (транзакции БД); "
        "пауза 0,1 с между PUT к МойСклад; шаблон — по **template_key** товара в SQLite."
    )
    batch_limit = st.number_input(
        "Размер батча (макс. 50)",
        min_value=1,
        max_value=50,
        value=50,
        key="sync_batch_limit",
    )
    if st.session_state.get("dry_run", True):
        st.warning("DRY_RUN активен — запросы к API не отправляются")

    if st.button("▶️ Генерировать все (status=new)", key="sync_batch_gen"):
        st.session_state.setdefault("preview", {})
        with get_conn() as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                SELECT id FROM products
                WHERE generation_status = 'new'
                ORDER BY id
                LIMIT ?
                """,
                (int(batch_limit),),
            )
            new_ids = [int(r[0]) for r in cur.fetchall()]
        if not new_ids:
            st.info("Нет товаров со статусом new.")
        else:
            total = len(new_ids)
            bar = st.progress(0.0, text=f"Обработано 0 из {total}")
            status_ph = st.empty()
            processed = 0
            for start in range(0, total, 5):
                chunk = new_ids[start : start + 5]

                def _progress_cb(cur_i: int, tot: int, *, off: int = start, ntot: int = total) -> None:
                    done = min(off + cur_i, ntot)
                    bar.progress(done / ntot if ntot else 0.0, text=f"Обработано {done} из {ntot}")
                    status_ph.caption(f"Чанк: id {chunk[0]}…{chunk[-1]} ({done}/{ntot})")

                with get_conn() as conn:
                    result = batch_generate_previews(
                        [str(x) for x in chunk],
                        conn,
                        _progress_cb,
                    )
                for pid_str, gen in result.items():
                    if gen is None:
                        continue
                    pid = int(pid_str)
                    product = load_product_for_workflow(pid)
                    if not product:
                        continue
                    chash = compute_source_hash(product, _fitment_dicts(pid))
                    st.session_state["preview"][pid] = {
                        "preview_name": gen.name,
                        "preview_description": gen.description,
                        "candidate_hash": chash,
                    }
                processed += len(chunk)
                bar.progress(
                    min(processed, total) / total,
                    text=f"Обработано {min(processed, total)} из {total}",
                )
            bar.empty()
            status_ph.empty()
        st.rerun()
        st.stop()

    if st.button("🚀 Синхронизировать все (status=review)", key="sync_batch_all"):
        preview = st.session_state.get("preview") or {}
        # Build list: in review, have preview, not locked, hash changed
        candidates: list[tuple[int, str, str, str]] = []
        with get_conn() as conn:
            conn.row_factory = sqlite3.Row
            for pid_raw, pdata in list(preview.items()):
                try:
                    pid = int(pid_raw)
                except (TypeError, ValueError):
                    continue
                if not isinstance(pdata, dict):
                    continue
                row = conn.execute(
                    """
                    SELECT id, generation_status, name_locked, source_hash
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
                pname = str(pdata.get("preview_name") or "")
                pdesc = str(pdata.get("preview_description") or "")
                ch = str(pdata.get("candidate_hash") or "")
                if ch == str(row["source_hash"] or ""):
                    continue
                candidates.append((pid, pname, pdesc, ch))
        candidates.sort(key=lambda x: x[0])
        candidates = candidates[: int(batch_limit)]
        if not candidates:
            st.error(
                "Нет товаров: статус review, есть preview, hash отличается, не заблокировано."
            )
        else:
            results: list[dict[str, Any]] = []
            n = len(candidates)
            bar = st.progress(0.0, text=f"Обработано 0 из {n}")
            sync_status = st.empty()
            for i, (pid, pname, pdesc, ch) in enumerate(candidates):
                sync_status.caption(f"Товар id={pid}…")
                code, detail = approve_and_sync(pid, pname, ch, pdesc, batch=True)
                ok = code == "ok"
                results.append(
                    {
                        "product_id": pid,
                        "status": "ok" if ok else code,
                        "error": "" if ok else (detail or ""),
                    }
                )
                bar.progress((i + 1) / n, text=f"Обработано {i + 1} из {n}")
                if i < n - 1:
                    time.sleep(0.1)
            bar.empty()
            sync_status.empty()
            st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)
