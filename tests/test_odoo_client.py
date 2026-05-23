"""Unit tests for Odoo JSON-RPC client (mocked HTTP — no live Odoo)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.odoo_client import OdooClient, OdooClientError  # noqa: E402


@pytest.fixture
def client() -> OdooClient:
    return OdooClient(
        url="https://erp.example.com",
        db="test_db",
        uid=5,
        api_secret="x" * 40,
    )


def test_build_payload_shape(client: OdooClient) -> None:
    payload = client._build_payload(1, "product.template", "search_read", [[]], {"limit": 1})
    args = payload["params"]["args"]
    assert args[0] == "test_db"
    assert args[1] == 5
    assert args[3] == "product.template"
    assert args[4] == "search_read"


def test_call_parses_result(client: OdooClient) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": [{"id": 1}]}
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "post", return_value=mock_resp) as post:
        out = client.call("res.users", "read", [[5], ["name"]])

    assert out == [{"id": 1}]
    post.assert_called_once()
    assert post.call_args.kwargs["json"]["params"]["method"] == "execute_kw"


def test_call_raises_on_rpc_error(client: OdooClient) -> None:
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"data": {"message": "Access Denied"}},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch.object(client._session, "post", return_value=mock_resp):
        with pytest.raises(OdooClientError, match="Access Denied"):
            client.call("product.template", "search_read", [[]])


def test_get_product_template_by_default_code(client: OdooClient) -> None:
    with patch.object(
        client,
        "search_read",
        return_value=[{"id": 3, "name": "Discount", "default_code": "DISC"}],
    ) as search_read:
        row = client.get_product_template_by_default_code("DISC")

    assert row is not None
    assert row["default_code"] == "DISC"
    search_read.assert_called_once()
    domain = search_read.call_args[0][1]
    assert domain == [["default_code", "=", "DISC"]]


def test_get_product_template_empty_code_raises(client: OdooClient) -> None:
    with pytest.raises(OdooClientError, match="non-empty"):
        client.get_product_template_by_default_code("  ")


def test_test_connection_success(client: OdooClient) -> None:
    with patch.object(client, "call", return_value=[{"name": "API Bot", "login": "bot@x"}]):
        ok, msg = client.test_connection()
    assert ok is True
    assert msg == "API Bot"


def test_test_connection_failure(client: OdooClient) -> None:
    with patch.object(client, "call", side_effect=OdooClientError("Access Denied")):
        ok, msg = client.test_connection()
    assert ok is False
    assert "Access Denied" in msg
