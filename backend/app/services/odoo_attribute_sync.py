"""Sync JSONL product attributes to Odoo ``product.template.attribute_line_ids``."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from app.models.product import Product
from app.services.attribute_parser import (
    format_attribute_value,
    sort_attribute_keys,
)
from app.services.odoo_client import OdooClient, OdooClientError
from app.services.text_utils import sanitize_token_value

logger = logging.getLogger(__name__)

JSONL_KEY_TO_ODOO_ATTRIBUTE_NAME: dict[str, str] = {
    "voltage_v": "Напряжение",
    "power_kw": "Мощность",
    "power_w": "Мощность",
    "amperage_ah": "Емкость",
    "base_type": "Тип цоколя",
    "volume_ml": "Объем",
    "weight_g": "Вес",
    "teeth_count": "Количество зубьев",
    "pins_count": "Количество контактов",
    "splines_count": "Количество шлицов",
    "diameter_mm": "Диаметр",
    "length_mm": "Длина",
    "thread_size": "Резьба",
    "gearbox_type": "Тип КПП",
    "gearbox_compatibility": "Совместимость КПП",
    "technology": "Технология",
    "composition_type": "Состав",
    "color_temp_k": "Цветовая температура",
    "form_factor": "Форм-фактор",
    "color": "Цвет",
}

_ODOO_CREATE_VARIANT = "no_variant"


def parse_product_attributes_json(product: Product) -> dict[str, Any]:
    """Load raw JSONL attributes stored on ``Product.attributes_json``."""
    raw = (getattr(product, "attributes_json", None) or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Invalid attributes_json for product_id=%s", product.id)
        return {}
    return payload if isinstance(payload, dict) else {}


def odoo_attribute_label(jsonl_key: str) -> str:
    key = jsonl_key.strip()
    if not key:
        return ""
    mapped = JSONL_KEY_TO_ODOO_ATTRIBUTE_NAME.get(key)
    if mapped:
        return mapped
    return key.replace("_", " ").strip().capitalize()


class OdooAttributeSyncService:
    """Resolve/create Odoo attributes and build ``attribute_line_ids`` commands."""

    def __init__(self, client: OdooClient) -> None:
        self._client = client
        self._attribute_ids: dict[str, int] = {}
        self._value_ids: dict[tuple[int, str], int] = {}

    def build_attribute_line_commands(
        self, attributes: Mapping[str, Any]
    ) -> list[tuple[int, int, dict[str, Any]]]:
        commands: list[tuple[int, int, dict[str, Any]]] = []
        for key in sort_attribute_keys(attributes):
            value = attributes[key]
            value_label = format_attribute_value(key, value)
            if not value_label:
                continue
            attr_name = odoo_attribute_label(key)
            if not attr_name:
                continue
            try:
                attribute_id = self._get_or_create_attribute(attr_name)
                value_id = self._get_or_create_attribute_value(attribute_id, value_label)
            except OdooClientError as exc:
                logger.warning(
                    "Skip attribute %r=%r: %s",
                    attr_name,
                    value_label,
                    exc,
                )
                continue
            commands.append(
                (
                    0,
                    0,
                    {
                        "attribute_id": attribute_id,
                        "value_ids": [(6, 0, [value_id])],
                    },
                )
            )
        return commands

    def merge_into_write_values(
        self,
        values: dict[str, Any],
        attributes: Mapping[str, Any],
    ) -> None:
        """Append ``attribute_line_ids`` replace commands to an existing write payload."""
        if not attributes:
            return
        try:
            line_commands = self.build_attribute_line_commands(attributes)
        except Exception as exc:
            logger.warning("Attribute line build failed: %s", exc, exc_info=True)
            return
        if not line_commands:
            return
        values["attribute_line_ids"] = [(5, 0, 0), *line_commands]

    def _get_or_create_attribute(self, name: str) -> int:
        cleaned = sanitize_token_value(name)
        if not cleaned:
            raise OdooClientError("attribute name is empty")
        cached = self._attribute_ids.get(cleaned.casefold())
        if cached is not None:
            return cached

        ids = self._client.search(
            "product.attribute",
            [["name", "=", cleaned]],
            limit=1,
        )
        if ids:
            attr_id = int(ids[0])
        else:
            attr_id = self._client.create(
                "product.attribute",
                {"name": cleaned, "create_variant": _ODOO_CREATE_VARIANT},
            )
        self._attribute_ids[cleaned.casefold()] = attr_id
        return attr_id

    def _get_or_create_attribute_value(
        self,
        attribute_id: int,
        value_name: str,
    ) -> int:
        cleaned = sanitize_token_value(value_name)
        if not cleaned:
            raise OdooClientError("attribute value is empty")
        cache_key = (attribute_id, cleaned.casefold())
        cached = self._value_ids.get(cache_key)
        if cached is not None:
            return cached

        ids = self._client.search(
            "product.attribute.value",
            [
                ["attribute_id", "=", attribute_id],
                ["name", "=", cleaned],
            ],
            limit=1,
        )
        if ids:
            value_id = int(ids[0])
        else:
            value_id = self._client.create(
                "product.attribute.value",
                {"name": cleaned, "attribute_id": attribute_id},
            )
        self._value_ids[cache_key] = value_id
        return value_id


def merge_product_attributes_into_write_values(
    client: OdooClient,
    product: Product,
    values: dict[str, Any],
) -> None:
    """
    Best-effort attribute sync for one ``product.template`` write payload.

    Failures are logged and do not raise — name/search_keywords sync continues.
    """
    attributes = parse_product_attributes_json(product)
    if not attributes:
        return
    try:
        OdooAttributeSyncService(client).merge_into_write_values(values, attributes)
    except Exception as exc:
        logger.warning(
            "Odoo attribute sync skipped for product_id=%s: %s",
            product.id,
            exc,
            exc_info=True,
        )
