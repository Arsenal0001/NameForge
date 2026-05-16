"""Templates page: CRUD template versions in SQLite."""

from __future__ import annotations

import sqlite3
from typing import Any

import pandas as pd
import streamlit as st

from src.db import get_conn
from src.fitment_repo import get_fitment, list_products_brief
from src.name_generator import generate_name
from src.template_engine import list_templates, save_template


def _load_product_full(product_id: int) -> dict[str, Any] | None:
    # Columns match src.db.init_db products table (no SELECT *).
    sql = """
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
            source_hash,
            created_at,
            updated_at
        FROM products
        WHERE id = ?
    """
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, (product_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def _format_is_active(v: Any) -> str:
    if v in (1, True):
        return "✅"
    return "—"


def _short_pattern(text: str, max_len: int = 80) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _templates_dataframe() -> pd.DataFrame:
    rows = list_templates()
    if not rows:
        return pd.DataFrame(
            columns=[
                "template_key",
                "version",
                "applicability_type",
                "is_active",
                "name_pattern",
            ]
        )
    data: list[dict[str, Any]] = []
    for r in rows:
        data.append(
            {
                "template_key": r.get("template_key", ""),
                "version": r.get("version", ""),
                "applicability_type": r.get("applicability_type", ""),
                "is_active": _format_is_active(r.get("is_active")),
                "name_pattern": _short_pattern(str(r.get("name_pattern") or "")),
            }
        )
    return pd.DataFrame(data)


st.title("Шаблоны")

if st.session_state.pop("_tpl_save_ok", False):
    st.success("Шаблон сохранён.")

# ═══ СЕКЦИЯ 1: Список шаблонов ═══
st.subheader("Шаблоны наименований")
st.dataframe(_templates_dataframe(), use_container_width=True, hide_index=True)

# ═══ СЕКЦИЯ 2: Создать / обновить шаблон ═══
st.subheader("Добавить версию шаблона")
col1, col2, col3 = st.columns(3)
with col1:
    template_key_in = st.text_input("template_key", key="tpl_key")
with col2:
    version_in = st.text_input("version", key="tpl_ver", placeholder="v2")
with col3:
    applicability_in = st.selectbox(
        "applicability_type",
        options=["fitment", "universal"],
        key="tpl_appl",
    )

name_pattern_in = st.text_area(
    "Шаблон",
    key="tpl_pattern",
    height=80,
    placeholder="{brand} {part_type} {article}\nдля {make} {model} {body} {years} {engine} {side}",
)
is_active_in = st.checkbox("Активировать сразу", value=True, key="tpl_active")

if st.button("💾 Сохранить шаблон", key="tpl_save"):
    key = (template_key_in or "").strip()
    version = (version_in or "").strip()
    ap = applicability_in
    pattern = (name_pattern_in or "").strip()
    if not key or not version or not ap or not pattern:
        st.error("Заполните все поля: template_key, version, тип применимости и шаблон.")
    else:
        try:
            save_template(
                key,
                version,
                ap,
                pattern,
                is_active_in,
            )
            st.session_state["_tpl_save_ok"] = True
            st.rerun()
        except (OSError, sqlite3.Error) as e:
            st.error(f"Не удалось сохранить: {e}")

# ═══ СЕКЦИЯ 3: Тест шаблона ═══
st.subheader("Тест шаблона на товаре")
all_tmpl = list_templates()
active_tmpl = [r for r in all_tmpl if int(r.get("is_active") or 0) == 1]
tpl_labels = [
    f"{r.get('template_key', '')} {r.get('version', '')} ({r.get('applicability_type', '')})"
    for r in active_tmpl
]

selected_tpl: dict[str, Any] | None = None
if not active_tmpl:
    st.info("Нет активных шаблонов. Активируйте шаблон в разделе выше или в таблице.")
    st.selectbox(
        "Выбрать шаблон",
        options=["(нет вариантов)"],
        disabled=True,
        key="tpl_test_pick_disabled",
    )
else:
    pick_idx = st.selectbox(
        "Выбрать шаблон",
        options=range(len(tpl_labels)),
        format_func=lambda i: tpl_labels[i],
        key="tpl_test_pick",
    )
    selected_tpl = active_tmpl[int(pick_idx)]

with get_conn() as conn:
    prows = list_products_brief(conn, limit=50)
prod_labels = [f"{r.get('article', '')} — {r.get('brand', '')}" for r in prows]

if not prows:
    st.warning("В базе нет товаров для теста (первые 50 записей).")
    product_id: int | None = None
else:
    pidx = st.selectbox(
        "Выбрать товар для теста",
        options=range(len(prod_labels)),
        format_func=lambda i: prod_labels[i],
        key="tpl_test_prod",
    )
    product_id = int(prows[int(pidx)]["id"])

if st.button("▶️ Протестировать", key="tpl_test_run"):
    if not active_tmpl:
        st.error("Нет активного шаблона для теста.")
    elif product_id is None:
        st.error("Нет товара для теста.")
    elif selected_tpl is None:
        st.error("Выберите шаблон.")
    else:
        product = _load_product_full(product_id)
        if not product:
            st.error("Товар не найден.")
        else:
            fitment_rows = [r.model_dump() for r in get_fitment(product_id)]
            pattern = str(selected_tpl.get("name_pattern") or "")
            result = generate_name(product, fitment_rows, pattern)
            if result.status == "generated":
                st.success(result.name)
            else:
                st.error(f"Ошибка: {result.missing_fields}")
            st.text_area("Описание", value=result.description, disabled=True, height=120)
            if result.warnings:
                w = result.warnings
                warn_text = ", ".join(w) if isinstance(w, list) else str(w)
                st.warning(f"Предупреждения: {warn_text}")

# ═══ СЕКЦИЯ 4: Справочник токенов ═══
with st.expander("📖 Доступные токены"):
    st.markdown(
        """
| Токен | Источник | Обязательный |
|-------|----------|--------------|
| `{brand}` | Бренд | да (fitment+universal) |
| `{part_type}` | Тип детали | да |
| `{article}` | OEM номер | да |
| `{make}` | Марка (primary fitment) | да (fitment) |
| `{model}` | Модель (primary fitment) | да (fitment) |
| `{body}` | Кузов | нет |
| `{years}` | Год от-до (из year_from/year_to) | нет |
| `{engine}` | Двигатель | нет |
| `{side}` | Сторона установки | нет |
"""
    )
