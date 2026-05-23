"""Tests for Odoo native attribute sync helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_BACKEND = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.odoo_attribute_sync import (  # noqa: E402
    OdooAttributeSyncService,
    merge_product_attributes_into_write_values,
    parse_product_attributes_json,
)


def test_parse_product_attributes_json() -> None:
    product = SimpleNamespace(
        id=1,
        attributes_json='{"power_kw": 1.2, "color": "Черный"}',
    )
    assert parse_product_attributes_json(product) == {
        "power_kw": 1.2,
        "color": "Черный",
    }


def test_build_attribute_line_commands_sorted_and_mapped() -> None:
    client = MagicMock()
    client.search.side_effect = [[], [], [], [], [], []]
    client.create.side_effect = [10, 100, 11, 101, 12, 102]

    service = OdooAttributeSyncService(client)
    commands = service.build_attribute_line_commands(
        {
            "color": "Черный",
            "volume_ml": 1000,
            "form_factor": "Аэрозоль",
        }
    )

    assert len(commands) == 3
    assert client.create.call_args_list[0].args[1]["create_variant"] == "no_variant"
    assert client.create.call_args_list[0].args[1]["name"] == "Объем"
    assert commands[0][2]["attribute_id"] == 10
    assert commands[0][2]["value_ids"] == [(6, 0, [100])]


def test_merge_into_write_values_clears_old_lines() -> None:
    client = MagicMock()
    service = OdooAttributeSyncService(client)
    service.build_attribute_line_commands = MagicMock(  # type: ignore[method-assign]
        return_value=[(0, 0, {"attribute_id": 1, "value_ids": [(6, 0, [2])]})]
    )
    values: dict = {"name": "Demo"}
    service.merge_into_write_values(values, {"color": "Черный"})
    assert values["attribute_line_ids"][0] == (5, 0, 0)


def test_merge_product_attributes_does_not_raise_on_failure() -> None:
    client = MagicMock()
    product = SimpleNamespace(id=1, attributes_json='{"color": "Черный"}')
    values: dict = {"name": "Demo"}

    with patch(
        "app.services.odoo_attribute_sync.OdooAttributeSyncService.merge_into_write_values",
        side_effect=RuntimeError("boom"),
    ):
        merge_product_attributes_into_write_values(client, product, values)

    assert values == {"name": "Demo"}
