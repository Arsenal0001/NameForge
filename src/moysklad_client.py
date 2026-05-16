"""HTTP client and helpers for the МойСклад JSON API."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, cast
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)


class MoySkladAuthError(Exception):
    """Raised when the API rejects credentials (HTTP 401)."""


class MoySkladAPIError(Exception):
    """Raised for non-success MoySklad API responses (except handled cases)."""


class MoySkladClient:
    """
    Synchronous JSON API client for MoySklad remap 1.2.

    ``dry_run`` only affects :meth:`update_product`; other methods always perform real HTTP calls.
    """

    GENERATION_STATUS_ATTR_NAME = "generation_status"

    def __init__(self, token: str, base_url: str, dry_run: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.dry_run = dry_run
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept-Encoding": "gzip",
            }
        )
        self._attr_map: dict[str, str] | None = None
        self._product_attr_rows: list[dict[str, Any]] | None = None
        self._productfolder_list: list[dict[str, Any]] | None = None
        self._productfolder_resolved: dict[str, dict[str, Any] | None] = {}

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        allow_404: bool = False,
        **kwargs: Any,
    ) -> dict:
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        logger.debug(
            "MoySklad %s %s kwargs=%s",
            method,
            url,
            {k: v for k, v in kwargs.items() if k != "headers"},
        )

        attempt = 0
        max_attempts = 2

        while attempt < max_attempts:
            logger.debug("REQUEST %s %s", method, url)
            response = self._session.request(method, url, **kwargs)

            logger.info("MoySklad response status=%s url=%s", response.status_code, url)

            if response.status_code == 401:
                raise MoySkladAuthError(
                    f"Authentication failed (401): {response.text[:500]}"
                )

            if response.status_code == 429:
                attempt += 1
                if attempt >= max_attempts:
                    raise MoySkladAPIError(
                        f"Rate limited (429) after retry: {response.text[:500]}"
                    )
                logger.warning("MoySklad 429; sleeping 5s before retry")
                time.sleep(5)
                continue

            if response.status_code == 404 and allow_404:
                return {}

            if not response.ok:
                raise MoySkladAPIError(
                    f"HTTP {response.status_code} for {url}: {response.text[:1000]}"
                )

            if response.status_code == 204 or not response.content:
                return {}

            try:
                return response.json()
            except ValueError as e:
                raise MoySkladAPIError(f"Invalid JSON from {url}: {e}") from e

        raise MoySkladAPIError("Unexpected retry loop exit")

    @staticmethod
    def _wrap_product_attribute_for_put(base_url: str, row: dict[str, Any]) -> dict[str, Any]:
        """
        Product PUT ``attributes`` rows must include ``meta`` with ``type: attributemetadata``;
        ``{"id", "value"}`` alone yields HTTP 400 (error 2014).
        """
        meta = row.get("meta")
        if isinstance(meta, dict) and str(meta.get("type") or "") == "attributemetadata":
            return row
        aid = str(row.get("id") or "").strip()
        if not aid:
            return row
        root = base_url.rstrip("/")
        return {
            "meta": {
                "href": f"{root}/entity/product/metadata/attributes/{aid}",
                "type": "attributemetadata",
                "mediaType": "application/json",
            },
            "value": row.get("value"),
        }

    def load_attribute_map(self) -> dict[str, str]:
        """
        GET /entity/product/metadata — map attribute ``name`` -> ``id`` (UUID).

        Result is cached on ``self._attr_map``.
        """
        if self._attr_map is not None:
            return self._attr_map

        data = self._request("GET", "entity/product/metadata")
        if not isinstance(data, dict):
            raise MoySkladAPIError(
                f"Expected dict, got {type(data)}: {str(data)[:100]}"
            )

        raw_attrs = data.get("attributes")
        attrs: list[Any] = []
        if raw_attrs is None:
            attrs = []
        elif isinstance(raw_attrs, list):
            attrs = raw_attrs
        elif isinstance(raw_attrs, dict):
            # Remap 1.2 often returns ``attributes`` as collection metadata (meta + size),
            # not an inlined list — load definitions from the attributes endpoint.
            am = raw_attrs.get("meta")
            if isinstance(am, dict) and am.get("href"):
                try:
                    attrs_data = self._request(
                        "GET",
                        "entity/product/metadata/attributes",
                        params={"limit": 1000, "offset": 0},
                    )
                except MoySkladAPIError as exc:
                    logger.warning(
                        "entity/product/metadata: attributes collection fetch failed: %s",
                        exc,
                    )
                    attrs = []
                else:
                    if isinstance(attrs_data, dict):
                        rows = attrs_data.get("rows")
                        attrs = list(rows) if isinstance(rows, list) else []
                    else:
                        attrs = []
            else:
                logger.warning(
                    "entity/product/metadata: attributes dict without meta.href; ignoring",
                )
        else:
            logger.warning(
                "entity/product/metadata: expected list or dict for attributes, got %s; ignoring",
                type(raw_attrs).__name__,
            )

        mapping: dict[str, str] = {}
        preserved: list[dict[str, Any]] = []
        for attr in attrs:
            if not isinstance(attr, dict):
                logger.warning(
                    "entity/product/metadata: skipping non-dict attribute entry: %r",
                    type(attr).__name__,
                )
                continue
            preserved.append(attr)
            name = attr.get("name")
            aid = attr.get("id")
            if isinstance(name, str) and aid:
                mapping[name] = str(aid)

        self._attr_map = mapping
        self._product_attr_rows = preserved
        return mapping

    def reset_attribute_map_cache(self) -> None:
        """Clear cached product metadata map so the next ``load_attribute_map()`` refetches."""
        self._attr_map = None
        self._product_attr_rows = None

    @staticmethod
    def _parse_customentity_dict_uuid_from_href(href: str) -> str | None:
        """
        Extract customentity **dictionary** UUID from ``customEntityMeta.href``.

        Shapes seen in Remap 1.2:

        * ``.../entity/customentity/{uuid}/...`` (metadata or element)
        * ``.../context/companysettings/metadata/customEntities/{uuid}`` (live accounts)
        """
        s = (href or "").strip()
        if not s:
            return None
        m = re.search(
            r"/entity/customentity/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/",
            s,
            flags=re.IGNORECASE,
        )
        if m:
            return m.group(1)
        m2 = re.search(
            r"/metadata/customEntities/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\?|$|/)",
            s,
            flags=re.IGNORECASE,
        )
        return m2.group(1) if m2 else None

    def brand_linked_customentity_dict_id(self, brand_attribute_uuid: str) -> str | None:
        """
        For a **product** custom attribute of type ``customentity``, return the linked
        user-dictionary UUID used in ``GET /entity/customentity/{id}`` (element list).

        ``brand_attribute_uuid`` is the attribute's ``id`` from ``entity/product/metadata``.
        """
        self.load_attribute_map()
        bid = (brand_attribute_uuid or "").strip()
        rows = self._product_attr_rows or []
        if not bid:
            return None
        for attr in rows:
            if str(attr.get("id") or "") != bid:
                continue
            meta = attr.get("customEntityMeta")
            if not isinstance(meta, dict):
                meta = attr.get("customentityMeta")  # defensive
            if not isinstance(meta, dict):
                logger.warning(
                    "MoySkladClient: attribute %s has no customEntityMeta; "
                    "cannot resolve customentity dictionary id",
                    bid,
                )
                return None
            href = str(meta.get("href") or "")
            parsed = self._parse_customentity_dict_uuid_from_href(href)
            if not parsed:
                logger.warning(
                    "MoySkladClient: could not parse dictionary id from customEntityMeta.href=%r",
                    href[:300],
                )
            return parsed
        logger.warning(
            "MoySkladClient: attribute id %s not found in product metadata",
            bid,
        )
        return None

    @staticmethod
    def _update_payload_for_log(payload: dict[str, Any]) -> str:
        """JSON preview for logs (no secrets — body is product fields + attribute ids)."""
        try:
            return json.dumps(payload, ensure_ascii=False)[:2500]
        except (TypeError, ValueError):
            return str(payload)[:2500]

    def _generation_status_filter_param(self, status: str) -> str | None:
        """Single-value ``filter`` fragment for ``generation_status``."""
        self.load_attribute_map()
        uuid = self._attr_map.get(self.GENERATION_STATUS_ATTR_NAME)
        if not uuid:
            logger.warning(
                "Attribute %r not found in metadata; skipping server-side status filter",
                self.GENERATION_STATUS_ATTR_NAME,
            )
            return None

        attr_meta_url = (
            f"{self.base_url}/entity/product/metadata/attributes/{uuid}"
        )
        return f"{attr_meta_url}={quote(status, safe='')}"

    @staticmethod
    def _attribute_value_as_text(val: Any) -> str:
        """Normalize MoySklad attribute ``value`` (string or reference dict) for comparison."""
        if val is None:
            return ""
        if isinstance(val, dict):
            return str(val.get("name") or val.get("value") or "")
        return str(val)

    def _filter_rows_by_generation_status(
        self, rows: list[dict], allowed: set[str]
    ) -> list[dict]:
        """Keep rows whose ``generation_status`` attribute value is in ``allowed``."""
        uuid = (self._attr_map or {}).get(self.GENERATION_STATUS_ATTR_NAME)
        if not uuid:
            return rows
        out: list[dict] = []
        for row in rows:
            attrs = row.get("attributes") or []
            val = self.get_attribute_value(attrs, uuid)
            text = self._attribute_value_as_text(val)
            if text in allowed:
                out.append(row)
        return out

    def get_products(
        self,
        status_filter: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        GET /entity/product with ``expand=attributes``.

        Optionally filter by custom attribute ``generation_status`` when present in metadata.
        """
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "expand": "attributes",
        }
        client_side_status: set[str] | None = None
        if status_filter:
            unique = list(dict.fromkeys(status_filter))
            if len(unique) == 1:
                filt = self._generation_status_filter_param(unique[0])
                if filt:
                    params["filter"] = filt
            else:
                client_side_status = set(unique)
                logger.debug(
                    "Multiple generation_status values — applying OR filter on this page only"
                )

        data = self._request("GET", "entity/product", params=params)
        rows = data.get("rows")
        if rows is None:
            rows = []
        else:
            rows = list(rows)

        if client_side_status:
            self.load_attribute_map()
            rows = self._filter_rows_by_generation_status(rows, client_side_status)

        return rows

    def get_product(self, ms_product_id: str) -> dict | None:
        """GET /entity/product/{id}?expand=attributes — ``None`` if 404."""
        endpoint = f"entity/product/{ms_product_id}"
        data = self._request(
            "GET",
            endpoint,
            params={"expand": "attributes"},
            allow_404=True,
        )
        if not data:
            return None
        return data

    def _all_productfolder_rows(self) -> list[dict[str, Any]]:
        """Paginated GET /entity/productfolder (cached for client lifetime)."""
        if self._productfolder_list is not None:
            return self._productfolder_list
        all_rows: list[dict[str, Any]] = []
        offset = 0
        limit = 1000
        while True:
            data = self._request(
                "GET",
                "entity/productfolder",
                params={"limit": limit, "offset": offset},
            )
            rows = data.get("rows") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                break
            for row in rows:
                if isinstance(row, dict):
                    all_rows.append(row)
            if len(rows) < limit:
                break
            offset += len(rows)
        self._productfolder_list = all_rows
        return all_rows

    def resolve_productfolder_for_put(self, path_name: str) -> dict[str, Any] | None:
        """
        Find product folder by full ``pathName``; return value for product PUT
        (``{meta: {href, type, mediaType}}``). API rejects ``pathName``-only; needs ``meta`` (error 2014).
        """
        want = (path_name or "").strip()
        if not want:
            return None
        if want in self._productfolder_resolved:
            got = self._productfolder_resolved[want]
            return dict(got) if got is not None else None

        for row in self._all_productfolder_rows():
            pn = str(row.get("pathName") or row.get("path_name") or "").strip()
            if pn != want:
                continue
            meta = row.get("meta")
            if not isinstance(meta, dict) or not meta.get("href"):
                self._productfolder_resolved[want] = None
                return None
            out: dict[str, Any] = {
                "meta": {
                    "href": str(meta.get("href")),
                    "type": str(meta.get("type") or "productfolder"),
                    "mediaType": str(meta.get("mediaType") or "application/json"),
                }
            }
            mhref = meta.get("metadataHref")
            if isinstance(mhref, str) and mhref.strip():
                out["meta"]["metadataHref"] = mhref.strip()
            self._productfolder_resolved[want] = out
            return out
        self._productfolder_resolved[want] = None
        return None

    def ensure_productfolder(self, path_name: str) -> dict[str, Any] | None:
        """
        Find product folder by full ``pathName`` or create it if missing.
        Returns value for product PUT (``{meta: ...}``).
        """
        want = (path_name or "").strip()
        if not want:
            return None
            
        existing = self.resolve_productfolder_for_put(want)
        if existing:
            return existing
            
        parts = [p.strip() for p in want.split("/")]
        parent_meta = None
        current_path = ""
        
        for i, part in enumerate(parts):
            if not part:
                continue
            if i == 0:
                current_path = part
            else:
                current_path = f"{current_path}/{part}"
                
            existing_part = self.resolve_productfolder_for_put(current_path)
            if existing_part:
                parent_meta = existing_part["meta"]
            else:
                payload = {"name": part}
                if parent_meta:
                    payload["productFolder"] = {"meta": parent_meta}
                
                if self.dry_run:
                    logger.info("dry_run POST entity/productfolder payload=%s", payload)
                    parent_meta = {
                        "href": f"{self.base_url}/entity/productfolder/mock-uuid",
                        "type": "productfolder",
                        "mediaType": "application/json"
                    }
                    self._productfolder_resolved[current_path] = {"meta": parent_meta}
                    continue
                
                try:
                    logger.info("Creating product folder: %s", current_path)
                    resp = self._request("POST", "entity/productfolder", json=payload)
                    
                    if self._productfolder_list is not None:
                        self._productfolder_list.append(resp)
                    
                    self._productfolder_resolved.pop(current_path, None)
                    meta = resp.get("meta")
                    if not meta:
                        logger.error("No meta in product folder creation response")
                        return None
                        
                    parent_meta = {
                        "href": str(meta.get("href")),
                        "type": str(meta.get("type") or "productfolder"),
                        "mediaType": str(meta.get("mediaType") or "application/json"),
                    }
                    if "metadataHref" in meta:
                        parent_meta["metadataHref"] = str(meta["metadataHref"])
                        
                    self._productfolder_resolved[current_path] = {"meta": parent_meta}
                except Exception as e:
                    logger.error("Failed to create product folder %s: %s", current_path, e)
                    return None
                    
        return {"meta": parent_meta} if parent_meta else None

    def update_product(
        self,
        ms_product_id: str,
        payload: dict,
        *,
        directory_cache: Any | None = None,
        brand: str | None = None,
    ) -> dict:
        """
        PUT /entity/product/{id} with ``name``, ``description``, ``attributes``.
        When ``dry_run``, log and return stub dict.

        For customentity «Бренд»: pass ``directory_cache`` and ``brand`` to append
        a resolved ``meta`` attribute (string-only values are ignored by MS otherwise).
        """
        if self.dry_run:
            logger.info(
                "dry_run PUT entity/product/%s payload=%s",
                ms_product_id,
                self._update_payload_for_log(cast(dict[str, Any], payload)),
            )
            return {"dry_run": True, "payload": payload}

        send = cast(dict[str, Any], dict(payload))
        if directory_cache is not None and brand and str(brand).strip():
            attrs = list(send.get("attributes") or [])
            send["attributes"] = attrs
            resolved = directory_cache.resolve_brand(str(brand).strip())
            buid = directory_cache.brand_attribute_uuid()
            if resolved and buid:
                attrs.append({"id": buid, "value": resolved})
                logger.info(
                    "update_product: brand resolved for PUT ms_id=%s href=%s",
                    ms_product_id,
                    str((resolved.get("meta") or {}).get("href") or "")[:120],
                )
            elif not resolved:
                logger.warning(
                    "update_product: brand %r not resolved in DirectoryCache; omitting brand attribute",
                    brand,
                )
            elif not buid:
                logger.warning(
                    "update_product: brand attribute uuid missing; omitting brand attribute",
                )

        raw_attrs = list(send.get("attributes") or [])
        send["attributes"] = [
            self._wrap_product_attribute_for_put(self.base_url, a) for a in raw_attrs
        ]

        logger.info(
            "PUT entity/product/%s payload_preview=%s",
            ms_product_id,
            self._update_payload_for_log(cast(dict[str, Any], send)),
        )
        endpoint = f"entity/product/{ms_product_id}"
        return self._request("PUT", endpoint, json=send)

    @staticmethod
    def get_attribute_value(attributes: list[dict], attr_uuid: str) -> Any:
        """
        Find attribute dict where ``id`` equals ``attr_uuid``; return ``value`` or ``None``.
        """
        for attr in attributes:
            if attr.get("id") == attr_uuid:
                return attr.get("value")
        return None
