from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _PROJECT_ROOT / ".env"


def resolve_sqlite_database_url(raw_url: str, *, project_root: Path) -> str:
    """
    Normalize SQLite URLs to an absolute filesystem path anchored at ``project_root``.

    Relative paths such as ``sqlite:///./data/autoname.db`` must not depend on the
    process CWD (e.g. when uvicorn is started from ``backend/``).
    """
    if not raw_url.startswith("sqlite"):
        return raw_url
    if ":memory:" in raw_url:
        return raw_url

    path_part = raw_url.removeprefix("sqlite:///").removeprefix("sqlite://")
    if not path_part:
        return raw_url

    db_path = Path(path_part)
    if not db_path.is_absolute():
        db_path = (project_root / db_path).resolve()
    else:
        db_path = db_path.resolve()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"

class Settings(BaseSettings):
    DATABASE_URL: str
    ODOO_URL: str
    ODOO_DB: str
    ODOO_UID: int = Field(
        default=0,
        description="Numeric res.users id for the dedicated NameForge API account",
    )
    ODOO_API_KEY: str = Field(default="", description="40-char Odoo API key (preferred)")
    ODOO_USER: str = Field(default="", description="Login of the API user (informational)")
    ODOO_PASSWORD: str = Field(
        default="",
        description="Fallback RPC secret when ODOO_API_KEY is empty",
    )
    DRY_RUN: bool = Field(
        default=True,
        description="When true, Odoo writes are simulated (no HTTP write calls).",
    )

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.is_file() else None,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def _resolve_database_url(cls, url: str) -> str:
        return resolve_sqlite_database_url(url, project_root=_PROJECT_ROOT)

    @field_validator("DRY_RUN", mode="before")
    @classmethod
    def _parse_dry_run(cls, value: object) -> bool:
        if value is None:
            return True
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
        return True

    def odoo_api_secret(self) -> str:
        """Return the RPC secret: ODOO_API_KEY first, then ODOO_PASSWORD."""
        key = (self.ODOO_API_KEY or "").strip()
        if key:
            return key
        return (self.ODOO_PASSWORD or "").strip()


settings = Settings()
