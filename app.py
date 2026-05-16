"""Streamlit entrypoint for the AutoName desktop app (MVP)."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.db import GENERATION_STATUSES, get_conn, get_effective_db_path, init_db
from src.directory_cache import DirectoryCache
from src.moysklad_client import MoySkladClient

_DEFAULT_MS_BASE_URL = "https://api.moysklad.ru/remap/1.2"

_STATUS_LABELS: dict[str, tuple[str, str]] = {
    "new": ("⏳", "new"),
    "review": ("🔄", "review"),
    "approved": ("✅", "approved"),
    "error": ("❌", "error"),
    "locked": ("🔒", "locked"),
}

st.set_page_config(page_title="NameForge", layout="wide")


def _parse_dry_run(raw: str | None, *, default: bool = True) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _generation_status_counts() -> dict[str, int]:
    sql = """
        SELECT generation_status, COUNT(*)
        FROM products
        GROUP BY generation_status
    """
    with get_conn() as conn:
        rows = conn.execute(sql).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def _render_sidebar() -> None:
    with st.sidebar:
        st.header("NameForge")

        if "dry_run" not in st.session_state:
            st.session_state["dry_run"] = _parse_dry_run(
                os.environ.get("DRY_RUN"), default=True
            )

        st.toggle("🔒 DRY RUN", key="dry_run")
        if st.session_state.get("dry_run", True):
            st.warning("Запись отключена")

        with st.expander("База данных и API", expanded=False):
            st.caption("Путь к SQLite (фактический файл)")
            st.code(str(get_effective_db_path()), language=None)
            ms_base = (os.environ.get("MS_BASE_URL") or _DEFAULT_MS_BASE_URL).strip()
            st.caption("Базовый URL МойСклад")
            st.text(ms_base)
            if st.session_state.get("_ms_token_configured"):
                st.caption("Токен API: задан (значение не показывается)")
            else:
                st.caption("Токен API: не задан — укажите MS_API_TOKEN в .env")

        st.divider()

        counts = _generation_status_counts()
        st.caption("Статистика по статусам")
        for status in GENERATION_STATUSES:
            emoji, label = _STATUS_LABELS.get(status, ("•", status))
            n = counts.get(status, 0)
            st.metric(f"{emoji} {label}", n)

        st.divider()

        if st.button("🔄 Обновить справочники"):
            st.cache_data.clear()
            client = st.session_state.get("ms_client")
            if isinstance(client, MoySkladClient):
                client.reset_attribute_map_cache()
            dc = st.session_state.get("directory_cache")
            if isinstance(dc, DirectoryCache):
                dc.clear_cache()
            if st.session_state.get("_ms_token_configured") and client:
                try:
                    st.session_state["attr_map"] = client.load_attribute_map()
                    st.session_state.pop("_attr_map_load_warning", None)
                except Exception as exc:  # noqa: BLE001 — UI: keep app usable
                    st.session_state["attr_map"] = {}
                    st.session_state["_attr_map_load_warning"] = (
                        f"Не удалось загрузить справочник атрибутов: {exc}"
                    )
            st.rerun()

        st.caption("v0.1.0")

        if not st.session_state.get("_ms_token_configured"):
            st.warning(
                "MS_API_TOKEN не задан в .env — запросы к API МойСклад недоступны."
            )
        msg = st.session_state.get("_attr_map_load_warning")
        if msg:
            st.warning(msg)


if "_nameforge_initialized" not in st.session_state:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    load_dotenv()

    from src.config import validate_startup_env

    validate_startup_env()

    init_db()

    token = (os.environ.get("MS_API_TOKEN") or "").strip()
    base_url = (os.environ.get("MS_BASE_URL") or _DEFAULT_MS_BASE_URL).strip()
    dry_run = _parse_dry_run(os.environ.get("DRY_RUN"), default=True)

    st.session_state["preview"] = {}
    st.session_state["attr_map"] = {}
    st.session_state["_ms_token_configured"] = bool(token)

    client = MoySkladClient(token or "", base_url, dry_run=dry_run)
    st.session_state["ms_client"] = client
    st.session_state["directory_cache"] = DirectoryCache(client) if token else None

    if token:
        try:
            st.session_state["attr_map"] = client.load_attribute_map()
            st.session_state.pop("_attr_map_load_warning", None)
        except Exception as exc:  # noqa: BLE001 — bootstrap: keep app usable without API
            st.session_state["attr_map"] = {}
            st.session_state["_attr_map_load_warning"] = (
                f"Не удалось загрузить справочник атрибутов: {exc}"
            )
    else:
        st.session_state.pop("_attr_map_load_warning", None)

    st.session_state["_nameforge_initialized"] = True

_render_sidebar()

if "ms_client" in st.session_state:
    st.session_state["ms_client"].dry_run = bool(st.session_state.get("dry_run", True))

pages = [
    st.Page("pages/01_queue.py", title="Очередь", icon="📋"),
    st.Page("pages/02_card.py", title="Карточка", icon="🃏"),
    st.Page("pages/03_templates.py", title="Шаблоны", icon="⚙️"),
    st.Page("pages/04_aliases.py", title="Алиасы", icon="🏷️"),
    st.Page("pages/05_sync.py", title="Синхронизация", icon="🔄"),
    st.Page("pages/06_naming.py", title="Наименования", icon="✏️"),
]
pg = st.navigation(pages)
pg.run()
