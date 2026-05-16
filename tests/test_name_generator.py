"""Tests for ``src.name_generator`` — pure functions, no I/O.

All tests match the finalized naming template:

    NAME: {part_type} {brand} {article[0]} для {make} {model} {body}
          {years} {engine} {side} {characteristics}
    DESC: Применяемость: {fitments}
          Кросс-номера: {article[1:]}
"""

from __future__ import annotations

from src.name_generator import GeneratedName, _side_already_in_part_type, generate_name

FITMENT_PATTERN = (
    "{part_type} {brand} {article} для {make} {model} {body} "
    "{years} {engine} {side} {characteristics}"
)
UNIVERSAL_PATTERN = "{part_type} {brand} {article} {side} {characteristics}"


def _fitment(**overrides: object) -> dict:
    base: dict = {
        "applicability_type": "fitment",
        "part_type": "Колодки тормозные",
        "brand": "BREMBO",
        "article": "P85075",
        "primary_make": "ВАЗ",
        "primary_model": "2110",
        "primary_body": "",
        "year_from": 2003,
        "year_to": 2012,
        "engine": "",
        "side_axis": "Передние",
        "characteristics": "",
    }
    base.update(overrides)
    return base


def _universal(**overrides: object) -> dict:
    base: dict = {
        "applicability_type": "universal",
        "part_type": "Фильтр масляный",
        "brand": "Bosch",
        "article": "W712/94",
        "primary_make": "",
        "primary_model": "",
        "primary_body": "",
        "year_from": None,
        "year_to": None,
        "engine": "",
        "side_axis": "",
        "characteristics": "",
    }
    base.update(overrides)
    return base


class TestFitmentNames:
    """Products with ``applicability_type='fitment'``."""

    def test_full_fitment_vaz_case(self) -> None:
        """Test case 1 + 12: full fitment with VAZ model prepend + no duplication."""
        p = _fitment()
        g = generate_name(p, [], FITMENT_PATTERN)
        assert isinstance(g, GeneratedName)
        assert g.status == "generated"
        assert g.name == (
            "Колодки тормозные BREMBO P85075 для ВАЗ 2110 2003-2012 Передние"
        )
        assert g.warnings == []

    def test_year_to_zero_s_prefix(self) -> None:
        """Test case 2: ``year_to=0`` emits ``с YYYY`` in the name."""
        p = _fitment(year_from=2015, year_to=0)
        g = generate_name(p, [], FITMENT_PATTERN)
        assert g.status == "generated"
        assert "с 2015" in g.name
        assert "н.в." not in g.name

    def test_no_make_model_no_dlia(self) -> None:
        """Test case 3: fitment without make/model — no ``для`` and no artifacts."""
        p = _fitment(primary_make="", primary_model="")
        g = generate_name(p, [], FITMENT_PATTERN)
        assert g.status == "generated"
        assert " для " not in g.name
        assert "{" not in g.name
        assert "}" not in g.name
        assert "  " not in g.name


class TestUniversalNames:
    """Products with ``applicability_type='universal'``."""

    def test_no_fitment_block_in_name(self) -> None:
        """Test case 4: universal products never include the fitment block."""
        p = _universal()
        g = generate_name(p, [], UNIVERSAL_PATTERN)
        assert g.status == "generated"
        assert g.name == "Фильтр масляный Bosch W712/94"
        assert " для " not in g.name

    def test_characteristics_at_end(self) -> None:
        """Test case 10: ``characteristics`` appear at the end of the name."""
        p = _universal(characteristics="синтетическое 5W-30 4л")
        g = generate_name(p, [], UNIVERSAL_PATTERN)
        assert g.status == "generated"
        assert g.name.endswith("синтетическое 5W-30 4л")
        assert g.name == "Фильтр масляный Bosch W712/94 синтетическое 5W-30 4л"


class TestSideDedupWhenEmbeddedInPartType:
    """Skip appending ``side_axis`` when it is already part of ``part_type``."""

    def test_kolodki_perednie_side_not_appended_twice(self) -> None:
        p = _fitment(
            part_type="Колодки тормозные Передние",
            side_axis="Передние",
        )
        g = generate_name(p, [], FITMENT_PATTERN)
        assert g.name.count("Передние") == 1

    def test_amortizator_zadniy_side_not_appended_twice(self) -> None:
        p = _fitment(
            part_type="Амортизатор Задний",
            side_axis="Задний",
        )
        g = generate_name(p, [], FITMENT_PATTERN)
        assert g.name.count("Задний") == 1

    def test_kolodki_perednie_with_levye_side_still_in_name(self) -> None:
        p = _fitment(
            part_type="Колодки тормозные Передние",
            side_axis="Левые",
        )
        g = generate_name(p, [], FITMENT_PATTERN)
        assert "Передние" in g.name
        assert "Левые" in g.name

    def test_filter_oil_with_side_axis_side_in_name(self) -> None:
        p = _universal(
            side_axis="Передний",
        )
        g = generate_name(p, [], UNIVERSAL_PATTERN)
        assert "Передний" in g.name

    def test_side_helper_pravaya_in_fara(self) -> None:
        assert _side_already_in_part_type("Фара (блок) Правая", "Правая") is True

    def test_side_helper_levy_not_in_kolodki_perednie(self) -> None:
        assert _side_already_in_part_type("Колодки тормозные Передние", "Левый") is False


class TestEdgeCases:
    """Brand skip, empty fields, multi-article, VAZ rules."""

    def test_brand_non_skipped(self) -> None:
        """Test case 5: brand ``NON`` is skipped with a warning."""
        p = _fitment(brand="NON")
        g = generate_name(p, [], FITMENT_PATTERN)
        assert "NON" not in g.name
        assert "brand_skipped" in g.warnings
        assert g.status == "review"

    def test_brand_empty_skipped(self) -> None:
        """Test case 6: empty brand is skipped with a warning."""
        p = _fitment(brand="")
        g = generate_name(p, [], FITMENT_PATTERN)
        assert "brand_skipped" in g.warnings
        assert g.status == "review"
        assert "  " not in g.name

    def test_multi_article_primary_name_cross_description(self) -> None:
        """Test case 7: multi-article splits into primary (name) + crosses (desc)."""
        p = _fitment(article="P85075; LPR05P; 21080")
        g = generate_name(p, [], FITMENT_PATTERN)
        assert g.status == "generated"
        assert "P85075" in g.name
        assert "LPR05P" not in g.name
        assert "21080" not in g.name
        assert "Кросс-номера: LPR05P | 21080" in g.description

    def test_empty_part_type_status_error(self) -> None:
        """Test case 8: empty ``part_type`` produces ``status='error'``."""
        p = _fitment(part_type="")
        g = generate_name(p, [], FITMENT_PATTERN)
        assert g.status == "error"
        assert "part_type" in g.missing_fields

    def test_empty_article_review_with_warning(self) -> None:
        """Test case 9: empty article emits ``status='review'`` + warning."""
        p = _fitment(article="")
        g = generate_name(p, [], FITMENT_PATTERN)
        assert g.status == "review"
        assert "missing_article" in g.warnings
        assert "{" not in g.name
        assert "}" not in g.name

    def test_cross_numbers_in_description_when_semicolon(self) -> None:
        """Test case 11: description carries cross-numbers when article has ``;``."""
        p = _universal(article="111; 222; 333")
        g = generate_name(p, [], UNIVERSAL_PATTERN)
        assert "Кросс-номера: 222 | 333" in g.description
        assert "111" in g.name
        assert "222" not in g.name

    def test_vaz_model_2110_prepended_not_duplicated(self) -> None:
        """Test case 12: VAZ model ``2110`` gets ``ВАЗ`` prefix without duplication."""
        p = _fitment(
            primary_make="ВАЗ",
            primary_model="2110",
            year_from=2003,
            year_to=2012,
        )
        g = generate_name(p, [], FITMENT_PATTERN)
        assert g.status == "generated"
        assert "ВАЗ 2110" in g.name
        assert "ВАЗ ВАЗ" not in g.name
        assert " для ВАЗ 2110 " in g.name + " "

    def test_vaz_model_without_make_no_prepend(self) -> None:
        """Without a make, a numeric model stays as-is (no prepend)."""
        p = _fitment(primary_make="", primary_model="2110")
        g = generate_name(p, [], FITMENT_PATTERN)
        assert g.status == "generated"
        assert "ВАЗ" not in g.name

    def test_candidate_hash_stable_for_same_inputs(self) -> None:
        """``candidate_hash`` is deterministic for identical inputs."""
        p = _fitment()
        g1 = generate_name(p, [], FITMENT_PATTERN)
        g2 = generate_name(p, [], FITMENT_PATTERN)
        assert g1.candidate_hash == g2.candidate_hash
        assert len(g1.candidate_hash) == 64

    def test_fitment_description_applies_primary_list(self) -> None:
        """Description assembles ``Применяемость:`` from ``fitment_rows``."""
        p = _fitment()
        rows = [
            {
                "make": "ВАЗ",
                "model": "2110",
                "body": "",
                "year_from": 2003,
                "year_to": 2012,
                "engine": "",
                "sort_order": 0,
                "id": 1,
            },
            {
                "make": "ВАЗ",
                "model": "2112",
                "body": "",
                "year_from": 2000,
                "year_to": 0,
                "engine": "",
                "sort_order": 1,
                "id": 2,
            },
        ]
        g = generate_name(p, rows, FITMENT_PATTERN)
        assert "Применяемость: ВАЗ 2110 2003-2012, ВАЗ 2112 с 2000" in g.description
