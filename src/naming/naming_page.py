"""Streamlit UI: generator, validator, bulk CSV (session_state only; no st.form)."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
import streamlit as st

from .name_model import PartName
from .name_parser import parse
from .name_validator import sanitize_csv_cell, validate


def _ensure_generator_state() -> None:
    st.session_state.setdefault("naming_category", "")
    st.session_state.setdefault("naming_fitment", "")
    st.session_state.setdefault("naming_brand", "NON")
    st.session_state.setdefault("naming_serial_blank", True)
    st.session_state.setdefault("naming_serial", 1)
    st.session_state.setdefault("naming_specs_df", pd.DataFrame({"spec": [""]}))
    st.session_state.setdefault("naming_colors_df", pd.DataFrame({"color": [""]}))


def _df_col_series(df: pd.DataFrame, preferred: str) -> list[Any]:
    if preferred in df.columns:
        return df[preferred].tolist()
    if len(df.columns) > 0:
        return df.iloc[:, 0].tolist()
    return []


def _tab_generator() -> None:
    _ensure_generator_state()
    st.subheader("Генератор")

    prefix_labels = ["— нет —", "Уценка", "!"]
    prefix_values = ["", "Уценка", "!"]
    p_idx = st.selectbox("Префикс", options=list(range(len(prefix_labels))), format_func=lambda i: prefix_labels[i], key="naming_prefix_ix")
    prefix = prefix_values[int(p_idx)]

    st.session_state["naming_category"] = st.text_input(
        "Категория {{...}}",
        value=st.session_state["naming_category"],
        key="naming_category_inp",
    )

    st.session_state["naming_fitment"] = st.text_area(
        "Применимость (>...<), через запятую",
        value=st.session_state["naming_fitment"],
        key="naming_fitment_ta",
    )
    raw_fit = st.session_state["naming_fitment"] or ""
    fit_parts = [x.strip() for x in raw_fit.split(",") if x.strip()]

    st.caption("Спеки `[...]` (редактор)")
    specs_df = st.data_editor(
        st.session_state["naming_specs_df"],
        num_rows="dynamic",
        column_config={"spec": st.column_config.TextColumn("spec", required=False)},
        key="naming_specs_ed",
    )
    if isinstance(specs_df, pd.DataFrame):
        st.session_state["naming_specs_df"] = specs_df
    specs = [str(x).strip() for x in _df_col_series(st.session_state["naming_specs_df"], "spec") if str(x).strip()]

    st.caption("Цвета `((...))` (редактор)")
    colors_df = st.data_editor(
        st.session_state["naming_colors_df"],
        num_rows="dynamic",
        column_config={"color": st.column_config.TextColumn("color", required=False)},
        key="naming_colors_ed",
    )
    if isinstance(colors_df, pd.DataFrame):
        st.session_state["naming_colors_df"] = colors_df
    colors = [str(x).strip() for x in _df_col_series(st.session_state["naming_colors_df"], "color") if str(x).strip()]

    st.session_state["naming_brand"] = st.text_input(
        "Бренд [[...]]",
        value=st.session_state["naming_brand"],
        key="naming_brand_inp",
    )

    blank = st.checkbox("Без серийного #N", value=st.session_state["naming_serial_blank"], key="naming_serial_cb")
    st.session_state["naming_serial_blank"] = blank
    serial: int | None = None
    if not blank:
        st.session_state["naming_serial"] = int(
            st.number_input(
                "#N",
                min_value=0,
                value=int(st.session_state.get("naming_serial", 1)),
                key="naming_serial_ni",
            )
        )
        serial = int(st.session_state["naming_serial"])

    part = PartName(
        prefix=prefix or None,
        category=st.session_state["naming_category"] or "",
        fitment=fit_parts if fit_parts else None,
        specs=specs,
        colors=colors,
        brand=st.session_state["naming_brand"] or "NON",
        serial=serial,
    )
    st.caption("Предпросмотр")
    st.code(part.to_string())


def _tab_validator() -> None:
    st.subheader("Валидатор")
    raw = st.text_area("Сырое наименование", height=160, key="naming_validate_raw")
    issues = validate(raw)
    if issues:
        rows = [{"code": i.code, "message": i.message} for i in issues]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        if raw.strip():
            st.success("Ошибок не найдено")


def _tab_bulk() -> None:
    st.subheader("Массовый импорт")
    up = st.file_uploader("CSV с колонкой «Наименование»", type=["csv"], key="naming_csv_up")
    if not up:
        return
    raw_bytes = up.getvalue()
    try:
        df = pd.read_csv(io.BytesIO(raw_bytes))
    except Exception as exc:  # noqa: BLE001 — UI
        st.error(f"Не удалось прочитать CSV: {exc}")
        return

    col = "Наименование"
    if col not in df.columns:
        if len(df.columns) == 1:
            col = str(df.columns[0])
        else:
            st.error("Нет колонки «Наименование».")
            return

    out_rows: list[dict[str, Any]] = []
    for i, cell in enumerate(df[col].tolist()):
        s = "" if cell is None or (isinstance(cell, float) and pd.isna(cell)) else str(cell)
        p = parse(s)
        errs = validate(s)
        err_txt = "; ".join(f"{e.code}: {e.message}" for e in errs)
        out_rows.append(
            {
                "row": i + 1,
                "raw": s,
                "category": p.category if p else "",
                "brand": p.brand if p else "",
                "specs": " | ".join(p.specs) if p else "",
                "colors": " | ".join(p.colors) if p else "",
                "fitment": " | ".join(p.fitment) if p and p.fitment else "",
                "errors": err_txt,
            }
        )

    st.dataframe(pd.DataFrame(out_rows), use_container_width=True, hide_index=True)

    out_df = pd.DataFrame(out_rows)
    for c in out_df.columns:
        out_df[c] = out_df[c].map(lambda v: sanitize_csv_cell(str(v)))
    csv_buf = io.StringIO()
    out_df.to_csv(csv_buf, index=False)
    st.download_button(
        "Скачать нормализованный CSV",
        data=csv_buf.getvalue().encode("utf-8-sig"),
        file_name="naming_normalized.csv",
        mime="text/csv",
        key="naming_dl_csv",
    )


def render_naming_page() -> None:
    st.title("Наименования")
    t1, t2, t3 = st.tabs(["Генератор", "Валидатор", "Массовый импорт"])
    with t1:
        _tab_generator()
    with t2:
        _tab_validator()
    with t3:
        _tab_bulk()
