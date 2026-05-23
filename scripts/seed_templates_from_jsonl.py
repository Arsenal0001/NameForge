#!/usr/bin/env python3
"""
Seed ``odoo_categories.name_pattern`` from golden-catalog JSONL statistics.

Maps majority ``golden_type`` per Odoo category group to formulas derived from
``NAMING_TEMPLATES_V2.md`` (TemplateEngine ``{token}`` syntax).

Run from project root:
    python scripts/seed_templates_from_jsonl.py              # dry-run (default)
    python scripts/seed_templates_from_jsonl.py --apply      # write to DB
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.schema_patches import apply_schema_patches  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.models.odoo_catalog_cache import OdooCategory  # noqa: E402
from app.services.template_service import get_template_engine  # noqa: E402

DEFAULT_JSONL = _ROOT / "data" / "odoo_master_catalog.jsonl"

# Registry: golden_type (from JSONL) -> name_pattern for TemplateEngine ({token} syntax).
GOLDEN_TYPE_FORMULAS: dict[str, str] = {
    # Interior / accessories (NAMING_TEMPLATES_V2 §3 group 1)
    "Коврик салона": (
        "{part_type} {installation} {fitment_core} {characteristics} {brand}"
    ),
    "Коврик багажника": (
        "{part_type} {installation} {fitment_core} {characteristics} {brand}"
    ),
    "Чехол сиденья": (
        "{part_type} {fitment_core} {characteristics} {brand}"
    ),
    "Чехлы сидений": (
        "{part_type} {fitment_core} {characteristics} {brand}"
    ),
    "Накидка на сиденье": (
        "{part_type} {fitment_core} {characteristics} {brand}"
    ),
    "Ароматизатор": (
        "{part_type} {installation} {characteristics} {brand}"
    ),
    # Lighting / electrics (group 2)
    "Лампа автомобильная": (
        "{part_type} {characteristics} {brand}"
    ),
    "Лампа светодиодная": (
        "{part_type} {characteristics} {brand}"
    ),
    "Автолампа": (
        "{part_type} {characteristics} {brand}"
    ),
    "Блок-фара": (
        "{part_type} {side} {fitment_core} {characteristics} {brand}"
    ),
    "Фара противотуманная": (
        "{part_type} {side} {fitment_core} {characteristics} {brand}"
    ),
    "Магнитола": (
        "{part_type} {fitment_core} {characteristics} {brand}"
    ),
    "Свеча зажигания": (
        "{part_type} {fitment_core} {brand}"
    ),
    # Suspension / brakes (group 4)
    "Амортизатор": (
        "{part_type} {side} {fitment_core} {characteristics} {brand}"
    ),
    "Колодки тормозные": (
        "{part_type} {side} {fitment_core} {characteristics} {brand}"
    ),
    "Диск тормозной": (
        "{part_type} {side} {fitment_core} {characteristics} {brand}"
    ),
    "Подшипник ступицы": (
        "{part_type} {side} {fitment_core} {characteristics} {brand}"
    ),
    # Engine / cooling (group 5)
    "Радиатор охлаждения": (
        "{part_type} {fitment_core} {characteristics} {brand}"
    ),
    "Радиатор охлаждения двигателя": (
        "{part_type} {fitment_core} {characteristics} {brand}"
    ),
    "Патрубок охлаждения": (
        "{part_type} {installation} {fitment_core} {characteristics} {brand}"
    ),
    # Fluids / consumables (group 6)
    "Масло моторное": (
        "{part_type} {characteristics} {brand}"
    ),
    "Аккумулятор": (
        "{part_type} {characteristics} {brand}"
    ),
    "Щетка стеклоочистителя": (
        "{part_type} {characteristics} {brand}"
    ),
    "Антикор": (
        "{part_type} {installation} {characteristics} {brand}"
    ),
    # Fallback (NAMING_TEMPLATES_V2 §3 bottom)
    "_fallback": (
        "{part_type} {fitment_core} {characteristics} {brand}"
    ),
}

CATEGORY_FIELD_KEYS = ("Категория (Группа)", "group", "Группа", "category")
GOLDEN_TYPE_FIELD_KEYS = ("Золотой тип", "golden_type", "Тип", "part_type")

MIN_ITEMS_PER_CATEGORY = 3
MAJORITY_THRESHOLD = 0.5


@dataclass(frozen=True, slots=True)
class CategorySeedPlan:
    category_label: str
    golden_type: str
    formula: str
    confidence_pct: float
    sample_count: int
    odoo_category_id: int | None = None
    odoo_category_name: str | None = None
    skipped_reason: str | None = None


def _normalize_category_key(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def _field(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        raw = row.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return ""


def _lookup_formula(golden_type: str) -> str | None:
    key = golden_type.strip()
    if not key:
        return None
    if key in GOLDEN_TYPE_FORMULAS:
        return GOLDEN_TYPE_FORMULAS[key]
    key_cf = key.casefold()
    for reg_key, formula in GOLDEN_TYPE_FORMULAS.items():
        if reg_key.casefold() == key_cf:
            return formula
    # Prefix match for variants like "Амортизатор передний"
    for reg_key, formula in GOLDEN_TYPE_FORMULAS.items():
        if reg_key == "_fallback":
            continue
        if key_cf.startswith(reg_key.casefold()):
            return formula
    return GOLDEN_TYPE_FORMULAS.get("_fallback")


def load_jsonl_groups(path: Path) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                print(f"WARNING: skip line {line_no}: invalid JSON ({exc})")
                continue
            if not isinstance(row, dict):
                print(f"WARNING: skip line {line_no}: expected JSON object")
                continue
            category = _field(row, CATEGORY_FIELD_KEYS)
            golden_type = _field(row, GOLDEN_TYPE_FIELD_KEYS)
            if not category:
                print(f"WARNING: skip line {line_no}: missing category/group")
                continue
            if not golden_type:
                print(f"WARNING: skip line {line_no}: missing golden type")
                continue
            groups[category].append(golden_type)
    return groups


def _majority(types: list[str]) -> tuple[str | None, float]:
    if len(types) < MIN_ITEMS_PER_CATEGORY:
        return None, 0.0
    counter = Counter(types)
    golden_type, count = counter.most_common(1)[0]
    confidence = count / len(types)
    if confidence <= MAJORITY_THRESHOLD:
        return None, confidence * 100.0
    return golden_type, confidence * 100.0


def build_category_index(categories: list[OdooCategory]) -> dict[str, OdooCategory]:
    index: dict[str, OdooCategory] = {}
    for cat in categories:
        for candidate in (cat.complete_name, cat.name):
            if candidate:
                index[_normalize_category_key(candidate)] = cat
        if cat.complete_name and "/" in cat.complete_name:
            leaf = cat.complete_name.split("/")[-1].strip()
            if leaf:
                index.setdefault(_normalize_category_key(leaf), cat)
    return index


def resolve_odoo_category(
    label: str, index: dict[str, OdooCategory]
) -> OdooCategory | None:
    key = _normalize_category_key(label)
    hit = index.get(key)
    if hit is not None:
        return hit
    # Try suffix match: JSONL "Автохимия/Антикор" vs Odoo "… / Антикор"
    leaf = label.split("/")[-1].strip()
    if leaf:
        hit = index.get(_normalize_category_key(leaf))
        if hit is not None:
            return hit
    for norm, cat in index.items():
        if norm.endswith(key) or key.endswith(norm):
            return cat
    return None


def plan_seeds(
    groups: dict[str, list[str]],
    category_index: dict[str, OdooCategory],
) -> list[CategorySeedPlan]:
    plans: list[CategorySeedPlan] = []
    for category_label, types in sorted(groups.items(), key=lambda x: x[0].casefold()):
        golden_type, confidence = _majority(types)
        if golden_type is None:
            reason = (
                f"too_few_items({len(types)})"
                if len(types) < MIN_ITEMS_PER_CATEGORY
                else f"no_majority({confidence:.1f}%)"
            )
            print(
                f"WARNING: skip «{category_label}» — {reason} "
                f"(n={len(types)})"
            )
            plans.append(
                CategorySeedPlan(
                    category_label=category_label,
                    golden_type="",
                    formula="",
                    confidence_pct=confidence,
                    sample_count=len(types),
                    skipped_reason=reason,
                )
            )
            continue

        formula = _lookup_formula(golden_type)
        if formula is None:
            print(
                f"WARNING: skip «{category_label}» — no formula for "
                f"golden_type={golden_type!r}"
            )
            plans.append(
                CategorySeedPlan(
                    category_label=category_label,
                    golden_type=golden_type,
                    formula="",
                    confidence_pct=confidence,
                    sample_count=len(types),
                    skipped_reason="formula_not_in_registry",
                )
            )
            continue

        odoo_cat = resolve_odoo_category(category_label, category_index)
        if odoo_cat is None:
            print(
                f"WARNING: skip «{category_label}» — Odoo category not in "
                f"local cache (sync catalog first)"
            )
            plans.append(
                CategorySeedPlan(
                    category_label=category_label,
                    golden_type=golden_type,
                    formula=formula,
                    confidence_pct=confidence,
                    sample_count=len(types),
                    skipped_reason="odoo_category_not_found",
                )
            )
            continue

        plans.append(
            CategorySeedPlan(
                category_label=category_label,
                golden_type=golden_type,
                formula=formula,
                confidence_pct=confidence,
                sample_count=len(types),
                odoo_category_id=odoo_cat.odoo_id,
                odoo_category_name=odoo_cat.complete_name or odoo_cat.name,
            )
        )
    return plans


def print_report(plans: list[CategorySeedPlan], *, dry_run: bool) -> None:
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"\n{'=' * 72}")
    print(f"  Template seed report ({mode})")
    print(f"{'=' * 72}")
    print(
        f"{'Категория Odoo':<36} {'Золотой тип':<22} "
        f"{'Уверен.':>8}  Формула"
    )
    print("-" * 72)

    applicable = [p for p in plans if p.skipped_reason is None]
    skipped = [p for p in plans if p.skipped_reason is not None]

    for plan in applicable:
        label = (plan.odoo_category_name or plan.category_label)[:35]
        gtype = plan.golden_type[:21]
        print(
            f"{label:<36} {gtype:<22} {plan.confidence_pct:>7.1f}%  "
            f"{plan.formula}"
        )

    print("-" * 72)
    print(
        f"Ready to seed: {len(applicable)} | Skipped: {len(skipped)} | "
        f"Total groups: {len(plans)}"
    )
    if dry_run and applicable:
        print("\nRe-run with --apply to write name_pattern to odoo_categories.")


def apply_plans(plans: list[CategorySeedPlan], *, dry_run: bool) -> int:
    applicable = [p for p in plans if p.skipped_reason is None and p.odoo_category_id]
    if dry_run or not applicable:
        return 0

    apply_schema_patches(engine)
    updated = 0
    db = SessionLocal()
    try:
        for plan in applicable:
            cat = db.get(OdooCategory, plan.odoo_category_id)
            if cat is None:
                print(
                    f"WARNING: odoo_id={plan.odoo_category_id} vanished — skip "
                    f"«{plan.category_label}»"
                )
                continue
            cat.name_pattern = plan.formula
            db.add(cat)
            updated += 1
        db.commit()
        get_template_engine().invalidate_cache()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed odoo_categories.name_pattern from JSONL golden types.",
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        default=DEFAULT_JSONL,
        help=f"Path to master catalog JSONL (default: {DEFAULT_JSONL})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write patterns to DB (default: dry-run report only)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dry_run = not args.apply

    jsonl_path = args.jsonl.resolve()
    if not jsonl_path.is_file():
        print(f"ERROR: JSONL not found: {jsonl_path}")
        return 1

    groups = load_jsonl_groups(jsonl_path)
    if not groups:
        print("ERROR: no category groups parsed from JSONL")
        return 1

    db = SessionLocal()
    try:
        categories = db.scalars(select(OdooCategory)).all()
    finally:
        db.close()

    category_index = build_category_index(list(categories))
    if not category_index:
        print(
            "WARNING: odoo_categories cache is empty — all matches will be skipped. "
            "Run Odoo catalog sync first."
        )

    plans = plan_seeds(groups, category_index)
    print_report(plans, dry_run=dry_run)

    if not dry_run:
        count = apply_plans(plans, dry_run=False)
        print(f"\nUpdated {count} odoo_categories.name_pattern row(s).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
