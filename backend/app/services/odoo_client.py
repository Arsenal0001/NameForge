"""
Odoo JSON-RPC client (direct ``execute_kw`` bypass).

See repository root ``odoo_api_knowledge.md``: do **not** use XML-RPC or
``authenticate`` — use ``POST {ODOO_URL}/jsonrpc`` with explicit DB, UID, and API key.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

# Odoo writes translatable fields (e.g. product.template.name) into the active lang.
DEFAULT_ODOO_RPC_LANG = "ru_RU"


class OdooClientError(RuntimeError):
    """Raised when Odoo configuration or JSON-RPC calls fail."""


class OdooClient:
    """
    Stateless JSON-RPC wrapper around Odoo ``execute_kw``.

    Credentials are taken from ``Settings`` unless overridden in the constructor.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        db: str | None = None,
        uid: int | None = None,
        api_secret: str | None = None,
        timeout: tuple[float, float] = (30.0, 180.0),
    ) -> None:
        self._url = (url or settings.ODOO_URL).rstrip("/") + "/jsonrpc"
        self._db = (db or settings.ODOO_DB).strip()
        self._uid = int(uid if uid is not None else settings.ODOO_UID)
        secret = (api_secret if api_secret is not None else settings.odoo_api_secret())
        self._api_secret = secret.strip()
        self._timeout = timeout
        self._rpc_id = 0
        self._session = requests.Session()

        if not self._db:
            raise OdooClientError("ODOO_DB is empty; set it in .env")
        if self._uid <= 0:
            raise OdooClientError(
                "ODOO_UID must be a positive integer (see odoo_api_knowledge.md)"
            )
        if not self._api_secret:
            raise OdooClientError(
                "Odoo API secret is empty; set ODOO_API_KEY or ODOO_PASSWORD in .env"
            )

    def _merge_rpc_kwargs(self, kwargs: dict[str, Any] | None) -> dict[str, Any]:
        """Ensure every ``execute_kw`` call uses the operator UI language (``ru_RU``)."""
        merged = dict(kwargs or {})
        ctx = dict(merged.get("context") or {})
        ctx["lang"] = DEFAULT_ODOO_RPC_LANG
        merged["context"] = ctx
        return merged

    @property
    def database(self) -> str:
        """Connected Odoo database name (``ODOO_DB``)."""
        return self._db

    def call(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Invoke ``execute_kw`` on ``model`` with positional ``args`` and keyword ``kwargs``."""
        self._rpc_id += 1
        payload = self._build_payload(
            self._rpc_id,
            model,
            method,
            args,
            self._merge_rpc_kwargs(kwargs),
        )
        try:
            http = self._session.post(self._url, json=payload, timeout=self._timeout)
            http.raise_for_status()
            body = http.json()
        except requests.RequestException as exc:
            logger.error("Odoo network error: %s", exc)
            raise OdooClientError(f"Odoo network error: {exc}") from exc

        return self._parse_response(body)

    def _build_payload(
        self,
        rpc_id: int,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [
                    self._db,
                    self._uid,
                    self._api_secret,
                    model,
                    method,
                    args if args is not None else [],
                    kwargs if kwargs is not None else {},
                ],
            },
        }

    def _parse_response(self, body: Any) -> Any:
        if not isinstance(body, dict):
            raise OdooClientError(f"Unexpected Odoo JSON-RPC payload type: {type(body)!r}")

        if body.get("error"):
            err = body["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            data = err.get("data") if isinstance(err, dict) else None
            if isinstance(data, dict) and data.get("message"):
                msg = str(data["message"])
            elif isinstance(data, str):
                msg = data
            logger.warning("Odoo RPC error: %s", msg)
            raise OdooClientError(f"Odoo RPC error: {msg}")

        return body.get("result")

    def batch_write(self, model: str, updates: list[tuple[list[int], dict[str, Any]]]) -> list[Any]:
        """
        Execute sequential ``write`` calls (one JSON-RPC request per record).

        Odoo deployments often reject HTTP JSON-RPC batch arrays with HTTP 400.
        """
        if not updates:
            return []

        results: list[Any] = []
        for ids, values in updates:
            results.append(self.write(model, ids, values))
        return results

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Alias for :meth:`call` (Odoo naming)."""
        return self.call(model, method, args, kwargs)

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        *,
        limit: int = 0,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        kw: dict[str, Any] = {"fields": fields}
        if limit:
            kw["limit"] = limit
        if offset:
            kw["offset"] = offset
        if order:
            kw["order"] = order
        out = self.call(model, "search_read", [domain], kw)
        if out is None:
            return []
        if not isinstance(out, list):
            raise OdooClientError(f"Unexpected search_read payload type: {type(out)!r}")
        return out

    def search(
        self,
        model: str,
        domain: list[Any],
        *,
        limit: int = 0,
        order: str | None = None,
    ) -> list[int]:
        """ORM ``search`` — returns record ids."""
        kw: dict[str, Any] = {}
        if limit:
            kw["limit"] = limit
        if order:
            kw["order"] = order
        out = self.call(model, "search", [domain], kw)
        if not out:
            return []
        if not isinstance(out, list):
            raise OdooClientError(f"Unexpected search payload type: {type(out)!r}")
        return [int(item) for item in out]

    def create(self, model: str, values: dict[str, Any]) -> int:
        """ORM ``create`` — returns new record id."""
        out = self.call(model, "create", [values])
        try:
            return int(out)
        except (TypeError, ValueError) as exc:
            raise OdooClientError(f"Unexpected create payload: {out!r}") from exc

    def write(self, model: str, ids: list[int], values: dict[str, Any]) -> Any:
        """ORM ``write`` for one batch of records."""
        if not ids:
            return True
        return self.call(model, "write", [ids, values])

    def test_connection(self) -> tuple[bool, str]:
        """
        Validate UID + API secret via ``res.users.read``.

        Returns ``(ok, message)`` — never raises for connectivity/auth failures.
        """
        try:
            rows = self.call("res.users", "read", [[self._uid], ["name", "login"]])
        except OdooClientError as exc:
            return False, str(exc)
        if not rows:
            return False, "Empty res.users read result"
        name = rows[0].get("name") or rows[0].get("login") or "unknown"
        return True, str(name)

    def get_product_template_by_default_code(
        self,
        default_code: str,
        *,
        fields: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """
        Fetch a single ``product.template`` row by ``default_code``.

        Returns ``None`` when no matching template exists.
        """
        code = default_code.strip()
        if not code:
            raise OdooClientError("default_code must be non-empty")

        read_fields = fields or [
            "id",
            "name",
            "default_code",
            "categ_id",
            "description_sale",
        ]
        rows = self.search_read(
            "product.template",
            [["default_code", "=", code]],
            read_fields,
            limit=1,
        )
        return rows[0] if rows else None

    def read_product_templates_by_ids(
        self,
        odoo_ids: list[int],
        *,
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Batch ``product.template`` read by numeric ids (read-only)."""
        ids = sorted({int(i) for i in odoo_ids if i})
        if not ids:
            return []
        read_fields = fields or ["id", "name", "default_code", "categ_id"]
        return self.search_read(
            "product.template",
            [["id", "in", ids]],
            read_fields,
        )

    def search_product_templates_by_category(
        self,
        category_id: int,
        *,
        fields: list[str] | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Read-only sample of ``product.template`` rows under a category tree."""
        read_fields = fields or ["id", "name", "default_code", "categ_id"]
        return self.search_read(
            "product.template",
            [["categ_id", "child_of", category_id]],
            read_fields,
            limit=limit,
            order="random()",
        )
