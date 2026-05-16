"""Tests for fitment_parser."""

from __future__ import annotations

from src.fitment_parser import parse_fitment_token, resolve_make_from_model


def test_parse_single_token_2107() -> None:
    assert parse_fitment_token("Prefix >2107< suffix") == "2107"


def test_parse_golf_vii() -> None:
    assert parse_fitment_token("X >Golf VII< Y") == "Golf VII"


def test_parse_no_token() -> None:
    assert parse_fitment_token("no angle brackets") is None


def test_resolve_vaz_2107() -> None:
    assert resolve_make_from_model("2107") == ("ВАЗ", "2107")


def test_resolve_unknown_golf() -> None:
    assert resolve_make_from_model("Golf") is None


def test_parse_empty() -> None:
    assert parse_fitment_token("") is None
