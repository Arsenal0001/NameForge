"""Aliases page: filters, table, add form, deactivate, CSV import."""

from __future__ import annotations

import io
import sqlite3
from typing import Any

import pandas as pd
import streamlit as st

from src.db import ALIAS_TYPES, get_conn


def _norm_alias(raw: str) -> str:
    return (raw or "").strip().lower()


def _csv_scalar_str(val: Any) -> str:
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()


def _format_is_active(v: Any) -> str:
    if v in (1, True):
        return "✅"
    return "—"


def _fetch_aliases(
    types_filter: list[str],
    search: str,
    show_inactive: bool,
) -> list[dict[str, Any]]:
    """types_filter: non-empty list of alias_type values to include."""
    if not types_filter:
        return []

    clauses: list[str] = ["alias_type IN (" + ", ".join("?" * len(types_filter)) + ")"]
    params: list[Any] = list(types_filter)

    if not show_inactive:
        clauses.append("is_active = 1")

    search = (search or "").strip()
    if search:
        clauses.append("(alias LIKE ? OR canonical_value LIKE ?)")
        needle = f"%{search}%"
        params.extend([needle, needle])

    sql = (
        "SELECT id, alias_type, scope_value, alias, canonical_value, is_active "
        "FROM aliases WHERE "
        + " AND ".join(clauses)
        + " ORDER BY alias_type, scope_value, alias_norm"
    )

    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, tuple(params))
        return [dict(r) for r in cur.fetchall()]


def _aliases_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "alias_type",
                "scope_value",
                "alias",
                "canonical_value",
                "is_active",
            ]
        )
    data: list[dict[str, Any]] = []
    for r in rows:
        data.append(
            {
                "alias_type": r.get("alias_type", ""),
                "scope_value": r.get("scope_value", ""),
                "alias": r.get("alias", ""),
                "canonical_value": r.get("canonical_value", ""),
                "is_active": _format_is_active(r.get("is_active")),
            }
        )
    return pd.DataFrame(data)


st.title("Алиасы")

if st.session_state.pop("_alias_saved_ok", False):
    st.success("Алиас сохранён.")
if st.session_state.pop("_alias_deactivated_ok", False):
    st.success("Алиас деактивирован.")
if st.session_state.pop("_alias_import_done", False):
    n = int(st.session_state.pop("_alias_import_added", 0))
    m = int(st.session_state.pop("_alias_import_skipped", 0))
    st.success(f"Импорт завершён: добавлено {n}, пропущено {m}.")

# ═══ Фильтры ═══
st.subheader("Фильтры")
fc1, fc2, fc3 = st.columns([2, 2, 1])
with fc1:
    type_pick = st.multiselect(
        "Тип алиаса",
        options=list(ALIAS_TYPES),
        default=list(ALIAS_TYPES),
        key="alias_filter_types",
    )
with fc2:
    search_in = st.text_input(
        "Поиск по alias / canonical_value",
        key="alias_search",
        placeholder="Подстрока…",
    )
with fc3:
    show_inactive = st.checkbox("Показывать неактивные", value=False, key="alias_show_inactive")

rows = _fetch_aliases(type_pick, search_in, show_inactive)

# ═══ Таблица ═══
st.subheader("Список")
st.dataframe(_aliases_dataframe(rows), use_container_width=True, hide_index=True)

# ═══ Деактивация ═══
st.subheader("Деактивировать")
if not rows:
    st.caption("Нет строк по текущим фильтрам.")
    sel_id: int | None = None
else:
    labels = [
        f"{r['id']} — [{r.get('alias_type')}] «{r.get('alias')}» → «{r.get('canonical_value')}»"
        for r in rows
    ]
    idx = st.selectbox(
        "Строка",
        options=range(len(rows)),
        format_func=lambda i: labels[i],
        key="alias_deactivate_pick",
    )
    sel_id = int(rows[int(idx)]["id"])

if st.button("🚫 Деактивировать", key="alias_deactivate_btn"):
    if sel_id is None:
        st.error("Нечего деактивировать.")
    else:
        try:
            with get_conn() as conn:
                conn.execute(
                    "UPDATE aliases SET is_active = 0 WHERE id = ?",
                    (sel_id,),
                )
            st.session_state["_alias_deactivated_ok"] = True
            st.rerun()
        except (OSError, sqlite3.Error) as e:
            st.error(f"Не удалось обновить: {e}")

# ═══ Форма добавления ═══
st.subheader("Добавить / заменить алиас")
c1, c2 = st.columns(2)
with c1:
    form_type = st.selectbox("alias_type", options=list(ALIAS_TYPES), key="alias_form_type")
    scope_val = st.text_input("scope_value", value="", key="alias_form_scope")
    alias_val = st.text_input("alias (исходное значение)", key="alias_form_alias")
with c2:
    canon_val = st.text_input("canonical_value", key="alias_form_canonical")
    is_act = st.checkbox("Активен", value=True, key="alias_form_active")

st.caption("alias_norm вычисляется автоматически: `alias.strip().lower()`")

if st.button("💾 Сохранить алиас", key="alias_form_save"):
    alias_raw = alias_val or ""
    canon_raw = (canon_val or "").strip()
    scope_s = (scope_val or "").strip()
    norm = _norm_alias(alias_raw)
    if not norm:
        st.error("Заполните поле alias (после trim не должно быть пусто).")
    elif not canon_raw:
        st.error("Заполните canonical_value.")
    else:
        try:
            with get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO aliases
                        (alias_type, scope_value, alias, alias_norm, canonical_value, is_active)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (alias_type, scope_value, alias_norm)
                    DO UPDATE SET
                        canonical_value = excluded.canonical_value,
                        is_active = excluded.is_active,
                        alias = excluded.alias
                    """,
                    (
                        form_type,
                        scope_s,
                        alias_raw.strip(),
                        norm,
                        canon_raw,
                        1 if is_act else 0,
                    ),
                )
            st.session_state["_alias_saved_ok"] = True
            st.rerun()
        except (OSError, sqlite3.Error) as e:
            st.error(f"Не удалось сохранить: {e}")

# ═══ Импорт CSV ═══
st.subheader("Массовый импорт из CSV")
uploaded = st.file_uploader(
    "CSV с колонками: alias_type, scope_value, alias, canonical_value",
    type=["csv"],
    key="alias_csv_upload",
)

if uploaded is not None:
    if st.button("Импортировать", key="alias_csv_run"):
        raw = uploaded.read()
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
        except Exception as e:  # noqa: BLE001 — UI
            st.error(f"Не удалось прочитать CSV: {e}")
        else:
            need = {"alias_type", "scope_value", "alias", "canonical_value"}
            cols = set(str(c).strip() for c in df.columns)
            if not need.issubset(cols):
                st.error(f"В файле должны быть колонки: {', '.join(sorted(need))}.")
            else:
                added = 0
                skipped = 0
                try:
                    with get_conn() as conn:
                        for _, row in df.iterrows():
                            at = _csv_scalar_str(row.get("alias_type"))
                            sv = _csv_scalar_str(row.get("scope_value"))
                            al_str = _csv_scalar_str(row.get("alias"))
                            cv = _csv_scalar_str(row.get("canonical_value"))
                            norm = _norm_alias(al_str)
                            if at not in ALIAS_TYPES or not norm or not cv:
                                skipped += 1
                                continue
                            cur = conn.execute(
                                """
                                INSERT OR IGNORE INTO aliases
                                    (alias_type, scope_value, alias, alias_norm, canonical_value, is_active)
                                VALUES (?, ?, ?, ?, ?, 1)
                                """,
                                (at, sv, al_str, norm, cv),
                            )
                            if cur.rowcount == 1:
                                added += 1
                            else:
                                skipped += 1
                except (OSError, sqlite3.Error) as e:
                    st.error(f"Ошибка импорта: {e}")
                else:
                    st.session_state["_alias_import_added"] = added
                    st.session_state["_alias_import_skipped"] = skipped
                    st.session_state["_alias_import_done"] = True
                    st.rerun()
