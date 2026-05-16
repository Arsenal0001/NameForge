"""Environment validation for NameForge (fail-fast on Streamlit startup)."""

from __future__ import annotations

import os
import warnings


def _truthy(raw: str | None, *, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def validate_startup_env() -> None:
    """
    Require MoySklad credentials. Warn when DRY_RUN is disabled.
    DB path follows ``src.db`` (optional ``DB_PATH`` override via env).
    """
    token = (
        os.environ.get("MS_TOKEN")
        or os.environ.get("MS_API_TOKEN")
        or os.environ.get("MOYSKLAD_TOKEN")
        or ""
    ).strip()
    login = (os.environ.get("MS_LOGIN") or "").strip()
    password = (os.environ.get("MS_PASSWORD") or "").strip()
    if not token and not (login and password):
        raise RuntimeError(
            "NameForge: укажите в .env MS_TOKEN (или MS_API_TOKEN / MOYSKLAD_TOKEN) "
            "либо пару MS_LOGIN + MS_PASSWORD для доступа к API МойСклад."
        )
    if not _truthy(os.environ.get("DRY_RUN"), default=True):
        warnings.warn(
            "DRY_RUN=false — реальные PUT в МойСклад разрешены. Убедитесь, что это намеренно.",
            stacklevel=2,
        )
