"""Tests for MoySkladClient — mocked HTTP only (no real requests)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.moysklad_client import MoySkladAPIError, MoySkladAuthError, MoySkladClient


def _make_client(**kwargs: object) -> MoySkladClient:
    defaults = {"token": "test-token", "base_url": "https://api.moysklad.ru/api/remap/1.2"}
    defaults.update(kwargs)
    return MoySkladClient(**defaults)


def _expected_put_attr(attr_id: str, value: object) -> dict:
    base = "https://api.moysklad.ru/api/remap/1.2"
    return {
        "meta": {
            "href": f"{base}/entity/product/metadata/attributes/{attr_id}",
            "type": "attributemetadata",
            "mediaType": "application/json",
        },
        "value": value,
    }


def test_parse_customentity_dict_uuid_from_href() -> None:
    href = (
        "https://api.moysklad.ru/api/remap/1.2/entity/customentity/"
        "7944ef04-f831-11e5-7a69-971500188b19/metadata"
    )
    assert (
        MoySkladClient._parse_customentity_dict_uuid_from_href(href)
        == "7944ef04-f831-11e5-7a69-971500188b19"
    )


def test_parse_customentity_dict_uuid_from_companysettings_href() -> None:
    href = (
        "https://api.moysklad.ru/api/remap/1.2/context/companysettings/"
        "metadata/customEntities/f4919878-664f-11ee-0a80-10eb0040d88f"
    )
    assert (
        MoySkladClient._parse_customentity_dict_uuid_from_href(href)
        == "f4919878-664f-11ee-0a80-10eb0040d88f"
    )


def test_brand_linked_customentity_dict_id_reads_metadata() -> None:
    brand_attr = "11111111-1111-1111-1111-111111111111"
    dict_id = "22222222-2222-2222-2222-222222222222"
    client = _make_client(dry_run=False)
    client._attr_map = {"dummy": "x"}
    client._product_attr_rows = [
        {
            "id": brand_attr,
            "name": "Бренд",
            "type": "customentity",
            "customEntityMeta": {
                "href": f"https://api.moysklad.ru/api/remap/1.2/entity/customentity/{dict_id}/metadata",
                "type": "customentitymetadata",
                "mediaType": "application/json",
            },
        }
    ]
    assert client.brand_linked_customentity_dict_id(brand_attr) == dict_id


def test_update_product_dry_run_no_http_returns_stub() -> None:
    client = _make_client(dry_run=True)
    client._session.request = MagicMock()

    payload = {"name": "Test", "description": "", "attributes": []}
    out = client.update_product("product-uuid", payload)

    client._session.request.assert_not_called()
    assert out == {"dry_run": True, "payload": payload}


def test_update_product_live_calls_put_returns_json() -> None:
    client = _make_client(dry_run=False)

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.ok = True
    mock_response.content = b'{"meta":{}}'
    mock_response.json.return_value = {"meta": {"href": "x"}, "name": "Updated"}

    client._session.request = MagicMock(return_value=mock_response)

    payload = {
        "name": "Updated",
        "description": "d1",
        "attributes": [{"id": "attr-1", "value": "v"}],
    }
    out = client.update_product("abc-id", payload)

    client._session.request.assert_called_once()
    call_kw = client._session.request.call_args
    assert call_kw[0][0] == "PUT"
    assert "entity/product/abc-id" in call_kw[0][1]
    expected = {
        "name": "Updated",
        "description": "d1",
        "attributes": [_expected_put_attr("attr-1", "v")],
    }
    assert call_kw[1]["json"] == expected
    assert out == {"meta": {"href": "x"}, "name": "Updated"}


def test_update_product_appends_resolved_brand_customentity() -> None:
    from src.directory_cache import DirectoryCache

    client = _make_client(dry_run=False)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.ok = True
    mock_response.content = b"{}"
    mock_response.json.return_value = {}
    client._session.request = MagicMock(return_value=mock_response)

    brand_meta = {"href": "https://api/ce/1", "type": "customentity", "mediaType": "application/json"}
    cache = MagicMock(spec=DirectoryCache)
    cache.resolve_brand = MagicMock(return_value={"meta": brand_meta})
    cache.brand_attribute_uuid = MagicMock(return_value="brand-attr-uuid")

    payload = {
        "name": "N",
        "description": "desc",
        "attributes": [{"id": "a", "value": "x"}],
    }
    client.update_product(
        "pid-1",
        payload,
        directory_cache=cache,
        brand="Bosch",
    )

    call_kw = client._session.request.call_args
    sent = call_kw[1]["json"]
    assert sent["name"] == "N"
    assert sent["description"] == "desc"
    attrs = sent["attributes"]
    assert attrs[0] == _expected_put_attr("a", "x")
    assert attrs[-1] == _expected_put_attr("brand-attr-uuid", {"meta": brand_meta})
    cache.resolve_brand.assert_called_once_with("Bosch")


def test_get_attribute_value_found() -> None:
    attrs = [
        {"id": "other-uuid", "value": "x"},
        {"id": "target-uuid", "value": "review"},
    ]
    assert MoySkladClient.get_attribute_value(attrs, "target-uuid") == "review"


def test_get_attribute_value_missing_returns_none() -> None:
    attrs = [{"id": "a", "value": 1}]
    assert MoySkladClient.get_attribute_value(attrs, "missing-uuid") is None


def test_request_401_raises_auth_error() -> None:
    client = _make_client()

    resp = MagicMock()
    resp.status_code = 401
    resp.ok = False
    resp.text = "Unauthorized"

    client._session.request = MagicMock(return_value=resp)

    with pytest.raises(MoySkladAuthError):
        client._request("GET", "entity/product/metadata")


def test_request_429_retries_once_sleep_called() -> None:
    client = _make_client()

    r429 = MagicMock()
    r429.status_code = 429
    r429.ok = False
    r429.text = "Too Many Requests"

    r200 = MagicMock()
    r200.status_code = 200
    r200.ok = True
    r200.content = b'{"rows":[]}'
    r200.json.return_value = {"rows": []}

    client._session.request = MagicMock(side_effect=[r429, r200])

    with patch("src.moysklad_client.time.sleep") as mock_sleep:
        result = client._request("GET", "entity/product")

    mock_sleep.assert_called_once_with(5)
    assert client._session.request.call_count == 2
    assert result == {"rows": []}


def test_request_405_raises_moysklad_api_error() -> None:
    client = _make_client()

    resp = MagicMock()
    resp.status_code = 405
    resp.ok = False
    resp.text = "Method Not Allowed"

    client._session.request = MagicMock(return_value=resp)

    with pytest.raises(MoySkladAPIError, match="405"):
        client._request("PUT", "entity/product/some-id", json={"name": "x"})
