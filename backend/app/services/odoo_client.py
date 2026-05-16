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

    def call(
        self,
        model: str,
        method: str,
        args: list[Any] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Invoke ``execute_kw`` on ``model`` with positional ``args`` and keyword ``kwargs``."""
        self._rpc_id += 1
        payload = self._build_payload(self._rpc_id, model, method, args, kwargs)
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
        Execute multiple ``write`` calls in a single HTTP request using JSON-RPC batching.
        
        :param updates: List of (ids, values) tuples.
        """
        if not updates:
            return []

        payloads = []
        for ids, values in updates:
            self._rpc_id += 1
            payloads.append(self._build_payload(self._rpc_id, model, "write", [ids, values]))

        try:
            http = self._session.post(self._url, json=payloads, timeout=self._timeout)
            http.raise_for_status()
            responses = http.json()
        except requests.RequestException as exc:
            logger.error("Odoo network error during batch: %s", exc)
            raise OdooClientError(f"Odoo network error during batch: {exc}") from exc

        if not isinstance(responses, list):
            # If server doesn't support batching, it might return a single error object
            return [self._parse_response(responses)]

        return [self._parse_response(resp) for resp in responses]

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
