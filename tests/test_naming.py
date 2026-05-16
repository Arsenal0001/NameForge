"""Tests for src.naming parse / validate / CSV sanitize."""

from __future__ import annotations

from src.naming.name_model import PartName
from src.naming.name_parser import parse
from src.naming.name_validator import NameIssue, sanitize_csv_cell, validate


def test_parse_roundtrip_reproduces_partname() -> None:
    original = PartName(
        prefix="Уценка",
        category="Фильтр масляный",
        fitment=["VW Golf"],
        specs=["OEM"],
        colors=["Черный"],
        brand="Mann",
        serial=12,
    )
    again = parse(original.to_string())
    assert again is not None
    assert again.model_dump() == original.model_dump()


def test_parse_none_without_category_braces() -> None:
    assert parse("no braces here [[X]]") is None
    assert parse("") is None


def test_validate_error_codes() -> None:
    long_s = "x" * 121 + " {{c}} [[b]]"
    codes = {i.code for i in validate(long_s)}
    assert "LEN" in codes

    assert any(i.code == "NO_CAT" for i in validate("[[Only]] brand"))
    assert any(i.code == "NO_BRAND" for i in validate("{{Only}} cat"))

    bad_bracket = "{{x}} ((! [[b]]"
    assert any(i.code == "BRACKET" for i in validate(bad_bracket))

    dup_spec = "{{a}} [s] [s] [[b]]"
    assert any(i.code == "DUP_SPEC" for i in validate(dup_spec))

    bad_color = "{{a}} ((Розовый)) [[b]]"
    assert any(i.code == "COLOR" for i in validate(bad_color))


def test_controlled_color_accepted() -> None:
    s = "{{a}} ((Черный)) [[b]]"
    assert not any(i.code == "COLOR" for i in validate(s))


def test_sanitize_csv_cell() -> None:
    assert sanitize_csv_cell("=1+1") == "1+1"
    assert sanitize_csv_cell("\t+evil") == "evil"
    assert sanitize_csv_cell("normal") == "normal"


def test_name_issue_is_namedtuple_like() -> None:
    issue = NameIssue("X", "msg")
    assert issue.code == "X"


def test_parse_serial_hash() -> None:
    p = parse("{{c}} [[NON]] #7")
    assert p is not None
    assert p.serial == 7


def test_partname_minimal_to_string() -> None:
    s = PartName(category="X", brand="Y").to_string()
    assert "{{X}}" in s and "[[Y]]" in s


def test_validate_ok_minimal() -> None:
    assert validate("{{a}} ((Черный)) [[b]]") == []
