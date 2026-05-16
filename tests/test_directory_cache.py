"""Tests for DirectoryCache — mocked HTTP via MoySkladClient._request."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.directory_cache import DirectoryCache


@pytest.fixture
def attr_map_min() -> dict:
    return {
        "Бренд": {"id": "brand-dict-uuid", "key": "brand"},
    }


def test_normalized_meta_keeps_metadata_href() -> None:
    meta = {
        "href": "https://api.test/entity/customentity/d/e1",
        "metadataHref": "https://api.test/context/companysettings/metadata/customEntities/d",
        "type": "customentity",
        "mediaType": "application/json",
        "uuidHref": "https://online.moysklad.ru/app/#x",
    }
    norm = DirectoryCache._normalized_element_meta(meta)
    assert norm is not None
    assert norm["metadataHref"] == meta["metadataHref"]
    assert norm["uuidHref"] == meta["uuidHref"]


def test_resolve_exact_name_returns_meta(attr_map_min: dict) -> None:
    client = MagicMock()
    meta = {"href": "https://api.test/entity/x/1", "type": "customentity", "mediaType": "application/json"}
    client._request = MagicMock(
        return_value={
            "rows": [
                {"id": "1", "name": "Bosch", "code": "B", "externalCode": "", "meta": meta},
            ]
        }
    )
    cache = DirectoryCache(client, attr_entries=attr_map_min)
    out = cache.resolve("brand-dict-uuid", "Bosch")
    assert out == {"meta": DirectoryCache._normalized_element_meta(meta), "name": "Bosch"}


def test_resolve_casefold(attr_map_min: dict) -> None:
    client = MagicMock()
    meta = {"href": "https://h/1", "type": "customentity", "mediaType": "application/json"}
    client._request = MagicMock(
        return_value={"rows": [{"id": "1", "name": "Mann", "code": "", "externalCode": "", "meta": meta}]}
    )
    cache = DirectoryCache(client, attr_entries=attr_map_min)
    out = cache.resolve("brand-dict-uuid", "mann")
    assert out == {"meta": DirectoryCache._normalized_element_meta(meta), "name": "Mann"}


def test_resolve_by_code(attr_map_min: dict) -> None:
    client = MagicMock()
    meta = {"href": "https://h/2", "type": "customentity", "mediaType": "application/json"}
    client._request = MagicMock(
        return_value={
            "rows": [{"id": "2", "name": "X", "code": "CODE99", "externalCode": "", "meta": meta}],
        }
    )
    cache = DirectoryCache(client, attr_entries=attr_map_min)
    out = cache.resolve("brand-dict-uuid", "CODE99")
    assert out == {"meta": DirectoryCache._normalized_element_meta(meta), "name": "X"}


def test_resolve_unknown_returns_none_and_warning(attr_map_min: dict, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    client = MagicMock()
    client._request = MagicMock(return_value={"rows": [{"id": "1", "name": "Only", "code": "", "meta": {"href": "u"}}]})
    cache = DirectoryCache(client, attr_entries=attr_map_min)
    with caplog.at_level(logging.WARNING):
        out = cache.resolve("brand-dict-uuid", "NoSuchBrand")
    assert out is None
    assert "no customentity match" in caplog.text.lower()


def test_resolve_brand_triggers_load(attr_map_min: dict) -> None:
    client = MagicMock()
    meta = {"href": "https://h/b", "type": "customentity", "mediaType": "application/json"}
    client._request = MagicMock(
        return_value={"rows": [{"id": "b", "name": "Febi", "code": "", "externalCode": "", "meta": meta}]}
    )
    cache = DirectoryCache(client, attr_entries=attr_map_min)
    assert "brand-dict-uuid" not in cache._cache
    out = cache.resolve_brand("Febi")
    assert out == {"meta": DirectoryCache._normalized_element_meta(meta), "name": "Febi"}
    client._request.assert_called()


def test_load_paginates_two_pages(attr_map_min: dict) -> None:
    client = MagicMock()

    def fake_request(method: str, ep: str, **kwargs: object) -> dict:
        off = (kwargs.get("params") or {}).get("offset", 0)
        if off == 0:
            return {"rows": [{"id": str(i), "name": f"N{i}", "code": "", "meta": {"href": f"http://{i}"}} for i in range(100)]}
        return {"rows": [{"id": "101", "name": "Last", "code": "", "meta": {"href": "http://101"}}]}

    client._request = MagicMock(side_effect=fake_request)
    cache = DirectoryCache(client, attr_entries=attr_map_min)
    cache.load("brand-dict-uuid")
    assert len(cache._cache["brand-dict-uuid"]) == 101
    assert client._request.call_count == 2
