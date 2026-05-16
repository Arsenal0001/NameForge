"""Cache and resolve MoySklad customentity rows (e.g. brand directory) by name/code."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_ATTR_MAP_PATH = Path(__file__).resolve().parent.parent / "config" / "attr_map.json"


def _default_attr_entries() -> dict[str, Any]:
    with open(_ATTR_MAP_PATH, encoding="utf-8") as f:
        return json.load(f)


class DirectoryCache:
    """Loads customentity rows and resolves string labels to ``meta`` for product PUT."""

    def __init__(self, client: Any, attr_entries: dict[str, Any] | None = None) -> None:
        self._client = client
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._attr_entries: dict[str, Any] = (
            attr_entries if attr_entries is not None else _default_attr_entries()
        )

    def clear_cache(self) -> None:
        """Drop loaded customentity rows (e.g. after «Обновить справочники» in UI)."""
        self._cache.clear()

    def brand_attribute_uuid(self) -> str | None:
        be = self._attr_entries.get("Бренд")
        if isinstance(be, dict):
            s = str(be.get("id") or "").strip()
            return s or None
        return None

    def brand_directory_uuid(self) -> str | None:
        """
        UUID of the **user dictionary** (element list), for
        ``GET /entity/customentity/{id}``.

        ``config/attr_map.json`` stores the **product attribute** id for «Бренд»;
        that id differs from the dictionary id — resolve via
        ``MoySkladClient.brand_linked_customentity_dict_id`` when available.
        """
        attr_id = self.brand_attribute_uuid()
        if not attr_id:
            return None
        fn = getattr(self._client, "brand_linked_customentity_dict_id", None)
        if callable(fn):
            linked = fn(attr_id)
            if isinstance(linked, str) and linked.strip():
                d = linked.strip()
                if d != attr_id:
                    logger.info(
                        "DirectoryCache: using linked customentity dictionary %s "
                        "(product attribute id %s)",
                        d,
                        attr_id,
                    )
                return d
        return attr_id

    def load(self, dict_uuid: str) -> None:
        """
        GET ``/entity/customentity/{dictionary_id}`` (Remap 1.2 — список элементов
        в поле ``rows``) with ``limit`` / ``offset`` pagination;
        cache dictionary_id → list[{id, name, code, externalCode, meta}].
        """
        if dict_uuid in self._cache:
            return

        all_rows: list[dict[str, Any]] = []
        offset = 0
        limit = 100

        while True:
            data = self._client._request(
                "GET",
                f"entity/customentity/{dict_uuid}",
                params={"limit": limit, "offset": offset},
            )
            rows = data.get("rows") if isinstance(data, dict) else None
            if rows is None:
                rows = []
            if not isinstance(rows, list):
                logger.warning(
                    "DirectoryCache: customentity %s unexpected rows type %s",
                    dict_uuid,
                    type(rows).__name__,
                )
                break

            for row in rows:
                if isinstance(row, dict):
                    all_rows.append(
                        {
                            "id": row.get("id"),
                            "name": row.get("name"),
                            "code": row.get("code"),
                            "externalCode": row.get("externalCode"),
                            "meta": row.get("meta"),
                        }
                    )

            if len(rows) < limit:
                break
            offset += len(rows)

        self._cache[dict_uuid] = all_rows
        logger.info(
            "DirectoryCache: loaded customentity dictionary %s — %s element(s)",
            dict_uuid,
            len(all_rows),
        )

    @staticmethod
    def _normalized_element_meta(meta: Any) -> dict[str, Any] | None:
        if not isinstance(meta, dict):
            return None
        href = meta.get("href")
        if not href:
            return None
        out: dict[str, Any] = {
            "href": str(href),
            "type": str(meta.get("type") or "customentity"),
            "mediaType": str(meta.get("mediaType") or "application/json"),
        }
        # MoySklad PUT rejects meta without metadataHref (error 2014) for product customentity attrs.
        mh = meta.get("metadataHref")
        if isinstance(mh, str) and mh.strip():
            out["metadataHref"] = mh.strip()
        uh = meta.get("uuidHref")
        if isinstance(uh, str) and uh.strip():
            out["uuidHref"] = uh.strip()
        return out

    def resolve(self, dict_uuid: str, value: str) -> dict[str, Any] | None:
        """
        Match value by: exact name, name.casefold(), code, externalCode.
        Returns ``{"meta": {...}, "name": ...}`` for MoySklad product PUT, or ``None``.
        """
        v = (value or "").strip()
        if not v:
            return None

        if dict_uuid not in self._cache:
            self.load(dict_uuid)

        entries = self._cache.get(dict_uuid) or []

        def row_to_value(row: dict[str, Any]) -> dict[str, Any] | None:
            norm = DirectoryCache._normalized_element_meta(row.get("meta"))
            if not norm:
                return None
            payload: dict[str, Any] = {"meta": norm}
            nm = row.get("name")
            if isinstance(nm, str) and nm.strip():
                payload["name"] = nm.strip()
            return payload

        for row in entries:
            name = row.get("name")
            if isinstance(name, str) and name == v:
                got = row_to_value(row)
                if got:
                    logger.info(
                        "DirectoryCache: resolved brand (exact name) dict=%s value=%r",
                        dict_uuid,
                        value,
                    )
                    return got

        vf = v.casefold()
        for row in entries:
            name = row.get("name")
            if isinstance(name, str) and name.strip().casefold() == vf:
                got = row_to_value(row)
                if got:
                    logger.info(
                        "DirectoryCache: resolved brand (casefold name) dict=%s value=%r",
                        dict_uuid,
                        value,
                    )
                    return got

        for row in entries:
            code = row.get("code")
            if code is not None and str(code).strip() == v:
                got = row_to_value(row)
                if got:
                    logger.info(
                        "DirectoryCache: resolved brand (code) dict=%s value=%r",
                        dict_uuid,
                        value,
                    )
                    return got

        for row in entries:
            ext = row.get("externalCode")
            if ext is not None and str(ext).strip() == v:
                got = row_to_value(row)
                if got:
                    logger.info(
                        "DirectoryCache: resolved brand (externalCode) dict=%s value=%r",
                        dict_uuid,
                        value,
                    )
                    return got

        logger.warning(
            "DirectoryCache: no customentity match for dict=%s value=%r",
            dict_uuid,
            value,
        )
        return None

    def resolve_brand(self, brand_name: str) -> dict[str, Any] | None:
        """
        Resolve brand label to a product-attribute ``value`` object for PUT:
        ``{"meta": {href, type, mediaType, metadataHref?, uuidHref?}, "name": ...}``.

        Loads elements for the linked **dictionary** id (see ``brand_directory_uuid``).
        """
        dict_uuid = self.brand_directory_uuid()
        if not dict_uuid:
            logger.warning("DirectoryCache: Бренд id missing in attr_map")
            return None
        return self.resolve(dict_uuid, brand_name)
