"""Управление маппингом part_type → MS productFolder (таблица category_mapping)."""

from __future__ import annotations

import sqlite3
from typing import Any

import pandas as pd
import streamlit as st

from src.category_mapper import resolve_folder
from src.db import get_conn


_SELECT_ALL = """
    SELECT id, part_type_pattern, ms_folder_path, priority, is_active, created_at
    FROM category_mapping
    ORDER BY is_active DESC, priority DESC, part_type_pattern
"""


def _load_mapping(active_only: bool) -> pd.DataFrame:
    sql = _SELECT_ALL
    if active_only:
        sql = sql.replace("FROM category_mapping", "FROM category_mapping WHERE is_active = 1")
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(sql).fetchall()]
    if not rows:
        return pd.DataFrame(
            columns=[
                "id",
                "part_type_pattern",
                "ms_folder_path",
                "priority",
                "is_active",
                "created_at",
            ]
        )
    return pd.DataFrame(rows)


def _persist_editor_changes(
    original: pd.DataFrame,
    edited: pd.DataFrame,
) -> tuple[int, int, int]:
    """
    Upsert edits, insert new rows (id is NaN), delete removed ids. Returns
    ``(updated, inserted, deleted)`` counters.
    """
    orig_by_id = {int(r["id"]): r for _, r in original.iterrows() if pd.notna(r.get("id"))}
    edited_ids: set[int] = set()

    updated = inserted = deleted = 0

    with get_conn() as conn:
        for _, r in edited.iterrows():
            pattern = str(r.get("part_type_pattern") or "").strip()
            folder = str(r.get("ms_folder_path") or "").strip()
            try:
                priority = int(r.get("priority") or 0)
            except (TypeError, ValueError):
                priority = 0
            is_active_int = 1 if bool(r.get("is_active", True)) else 0

            if not pattern or not folder:
                continue

            raw_id = r.get("id")
            if pd.isna(raw_id):
                conn.execute(
                    """
                    INSERT OR IGNORE INTO category_mapping
                        (part_type_pattern, ms_folder_path, priority, is_active)
                    VALUES (?, ?, ?, ?)
                    """,
                    (pattern, folder, priority, is_active_int),
                )
                inserted += 1
                continue

            row_id = int(raw_id)
            edited_ids.add(row_id)
            prev = orig_by_id.get(row_id)
            changed = True
            if prev is not None:
                changed = (
                    str(prev.get("part_type_pattern") or "").strip() != pattern
                    or str(prev.get("ms_folder_path") or "").strip() != folder
                    or int(prev.get("priority") or 0) != priority
                    or int(prev.get("is_active") or 0) != is_active_int
                )
            if changed:
                conn.execute(
                    """
                    UPDATE category_mapping
                    SET part_type_pattern = ?,
                        ms_folder_path    = ?,
                        priority          = ?,
                        is_active         = ?
                    WHERE id = ?
                    """,
                    (pattern, folder, priority, is_active_int, row_id),
                )
                updated += 1

        for row_id in orig_by_id:
            if row_id not in edited_ids:
                conn.execute("DELETE FROM category_mapping WHERE id = ?", (row_id,))
                deleted += 1

    return updated, inserted, deleted


def _bulk_apply_folder(limit: int = 500) -> int:
    """
    Set ``product_folder`` for products without one, skipping ``locked``.
    Returns the number of rows updated.
    """
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        candidates = conn.execute(
            """
            SELECT id, part_type
            FROM products
            WHERE (product_folder IS NULL OR TRIM(product_folder) = '')
              AND generation_status != 'locked'
            ORDER BY id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        n = 0
        for row in candidates:
            pid = int(row["id"])
            part_type = str(row["part_type"] or "").strip()
            folder = resolve_folder(part_type) if part_type else None
            if not folder:
                continue
            conn.execute(
                """
                UPDATE products
                SET product_folder = ?
                WHERE id = ?
                  AND (product_folder IS NULL OR TRIM(product_folder) = '')
                  AND generation_status != 'locked'
                """,
                (folder, pid),
            )
            n += 1

    return n


st.title("Категории → папки МойСклад")

# ═══ СЕКЦИЯ 1: Таблица category_mapping ═══
st.subheader("Правила маппинга")

active_only = st.checkbox(
    "Только активные",
    value=False,
    key="catmap_active_only",
)

original_df = _load_mapping(active_only)

if original_df.empty:
    st.info(
        "Правил нет. Добавьте строку в таблице ниже или запустите "
        "`python scripts/seed_category_mapping.py` для стартового набора."
    )

edited_df = st.data_editor(
    original_df,
    num_rows="dynamic",
    use_container_width=True,
    key="catmap_editor",
    column_config={
        "id": st.column_config.NumberColumn("id", disabled=True, width="small"),
        "part_type_pattern": st.column_config.TextColumn(
            "part_type_pattern",
            help="Точный текст или fnmatch (пример: «Колодки*», «Амортизатор*»).",
            required=True,
        ),
        "ms_folder_path": st.column_config.TextColumn(
            "ms_folder_path",
            help="Путь в МойСклад: «Тормозная система/Колодки»",
            required=True,
        ),
        "priority": st.column_config.NumberColumn(
            "priority",
            help="Выше значение → выше приоритет; точные > глоб при равном priority.",
            min_value=0,
            step=1,
            default=0,
        ),
        "is_active": st.column_config.CheckboxColumn(
            "is_active",
            default=True,
        ),
        "created_at": st.column_config.TextColumn(
            "created_at",
            disabled=True,
            width="small",
        ),
    },
    hide_index=True,
)

if st.button("💾 Сохранить изменения таблицы", key="catmap_save"):
    try:
        upd, ins, dele = _persist_editor_changes(original_df, edited_df)
        st.success(
            f"Сохранено: обновлено {upd}, добавлено {ins}, удалено {dele}."
        )
        st.rerun()
    except sqlite3.Error as e:
        st.error(f"Не удалось сохранить: {e}")

st.divider()

# ═══ СЕКЦИЯ 2: Тест маппинга ═══
st.subheader("Тест: какая папка МойСклад будет выбрана?")

test_input = st.text_input(
    "part_type",
    key="catmap_test_input",
    placeholder="Например: Колодки тормозные",
)
if st.button("▶️ Проверить", key="catmap_test_btn"):
    needle = (test_input or "").strip()
    if not needle:
        st.warning("Введите part_type для теста.")
    else:
        folder = resolve_folder(needle)
        if folder:
            st.success(f"«{needle}» → **{folder}**")
        else:
            st.info(f"Для «{needle}» правил не найдено.")

st.divider()

# ═══ СЕКЦИЯ 3: Bulk операции ═══
st.subheader("Массовое применение маппинга")

with get_conn() as conn:
    empty_folder_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM products
        WHERE (product_folder IS NULL OR TRIM(product_folder) = '')
          AND generation_status != 'locked'
        """
    ).fetchone()[0]

st.caption(
    f"Товаров без ``product_folder`` и не заблокированных: **{int(empty_folder_count)}**. "
    "Один клик обрабатывает до 500 товаров."
)

if st.button(
    "📂 Применить маппинг к товарам без папки (до 500)",
    key="catmap_bulk_apply",
    disabled=int(empty_folder_count) == 0,
):
    try:
        updated = _bulk_apply_folder(500)
        st.success(f"Обновлено товаров: {updated}")
        st.rerun()
    except sqlite3.Error as e:
        st.error(f"Ошибка БД: {e}")


# ═══ Сводка по правилам ═══
with st.expander("📊 Сводка"):
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        stats = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) AS active
            FROM category_mapping
            """
        ).fetchone()
    total = int((stats or {}).get("total") or 0)
    active = int((stats or {}).get("active") or 0)
    st.write(f"Всего правил: **{total}** · активных: **{active}**")

    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
                COALESCE(NULLIF(TRIM(product_folder), ''), '—') AS folder,
                COUNT(*) AS n
            FROM products
            GROUP BY folder
            ORDER BY n DESC
            LIMIT 20
            """
        ).fetchall()
    if rows:
        data: list[dict[str, Any]] = [
            {"folder": str(r["folder"]), "n": int(r["n"])} for r in rows
        ]
        st.dataframe(pd.DataFrame(data), use_container_width=True, hide_index=True)
