"""
Import products from MoySklad into local SQLite (products + fitments).

Run from project root:
  python scripts/import_from_ms.py --dry-run --limit 10
  python scripts/import_from_ms.py --limit 10
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_DEFAULT_MS_BASE = "https://api.moysklad.ru/api/remap/1.2"
_ATTR_MAP_PATH = _ROOT / "config" / "attr_map.json"

try:
    from src.naming.name_parser import parse as _name_parser_parse
except ImportError:
    _name_parser_parse = None  # type: ignore[assignment]

from src.db import GENERATION_STATUSES, get_conn, init_db  # noqa: E402
from src.fitment_parser import parse_fitment_token, resolve_make_from_model  # noqa: E402
from src.fitment_repo import FitmentRow, delete_all_fitment, save_fitment  # noqa: E402
from src.hash_utils import compute_source_hash  # noqa: E402


def _load_dotenv(path: Path) -> None:
    """Merge key=value pairs from ``path`` into ``os.environ`` (no override)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        os.environ.setdefault(key, val)


def _resolve_auth() -> tuple[str, dict[str, str]]:
    """
    Return (base_url, headers) for MoySklad JSON API (same env keys as setup_ms_attributes).

    Token: MS_TOKEN or MS_API_TOKEN / MOYSKLAD_TOKEN (Bearer).
    Else MS_LOGIN + MS_PASSWORD (Basic).
    """
    token = (
        os.environ.get("MS_TOKEN")
        or os.environ.get("MS_API_TOKEN")
        or os.environ.get("MOYSKLAD_TOKEN")
        or ""
    ).strip()
    login = (os.environ.get("MS_LOGIN") or "").strip()
    password = (os.environ.get("MS_PASSWORD") or "").strip()
    base = (os.environ.get("MS_BASE_URL") or _DEFAULT_MS_BASE).rstrip("/")

    if token:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        }
        return base, headers

    if login and password:
        raw = f"{login}:{password}".encode("utf-8")
        b64 = base64.b64encode(raw).decode("ascii")
        headers = {
            "Authorization": f"Basic {b64}",
            "Content-Type": "application/json",
            "Accept-Encoding": "gzip",
        }
        return base, headers

    print(
        "Missing MoySklad credentials in .env.\n"
        "Set one of:\n"
        "  - MS_TOKEN, MS_API_TOKEN, or MOYSKLAD_TOKEN (Bearer), or\n"
        "  - MS_LOGIN and MS_PASSWORD (Basic).\n"
        "Optional: MS_BASE_URL\n"
        f"Expected file: {_ROOT / '.env'}"
    )
    sys.exit(1)


def load_attr_map(path: Path) -> dict[str, str]:
    """
    Load config/attr_map.json and build reverse map {attribute_uuid: key}.

    Exit with error if any entry other than Бренд / Характеристики has an empty id.
    """
    if not path.is_file():
        print(
            f"Missing {path}.\n"
            "Create it via: python scripts/setup_ms_attributes.py\n"
            "Use --patch-missing after creating Бренд / Характеристики in MoySklad UI."
        )
        sys.exit(1)

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        print(f"Invalid attr_map.json: expected object at root, got {type(data).__name__}")
        sys.exit(1)

    id_to_key: dict[str, str] = {}
    for ms_name, entry in data.items():
        if not isinstance(entry, dict):
            print(f"Invalid attr_map entry for {ms_name!r}: expected object")
            sys.exit(1)
        aid = str(entry.get("id") or "").strip()
        key = str(entry.get("key") or "").strip()
        if not aid:
            if ms_name not in ("Бренд", "Характеристики"):
                print(
                    f"attr_map.json: empty id for attribute {ms_name!r} (key={key!r}). "
                    "Run scripts/setup_ms_attributes.py --patch-missing."
                )
                sys.exit(1)
            continue
        if not key:
            print(f"attr_map.json: empty key for attribute {ms_name!r}")
            sys.exit(1)
        id_to_key[aid] = key

    return id_to_key


def extract_attrs(ms_product: dict[str, Any], id_to_key: dict[str, str]) -> dict[str, Any]:
    """Extract custom attribute values handling customentity (nested dict) and booleans."""
    result: dict[str, Any] = {}
    for attr in ms_product.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        attr_id = str(attr.get("id") or "")
        key = id_to_key.get(attr_id)
        if not key:
            continue
        val = attr.get("value")
        if isinstance(val, dict):
            result[key] = str(val.get("name") or "")
        elif isinstance(val, bool):
            result[key] = 1 if val else 0
        elif val is None:
            result[key] = ""
        elif isinstance(val, (int, float)) and key in ("year_from", "year_to"):
            result[key] = int(val)
        elif isinstance(val, (int, float)) and key == "name_locked":
            result[key] = 1 if int(val) else 0
        else:
            result[key] = str(val)
    return result


def _fallback_brand_from_name(name: str) -> str:
    """Parse first [[Segment]] from product name when name_parser is absent."""
    m = re.search(r"\[\[([^\]]+)\]\]", name or "")
    if not m:
        return ""
    return m.group(1).strip()


def _parse_brand_fallback(name: str) -> tuple[str, bool]:
    """
    Return (brand, used_fallback). Respects name_parser.parse() when available;
    ignores placeholder brands NON / ? / empty.
    """
    if _name_parser_parse is not None:
        parsed = _name_parser_parse(name)
        if parsed is None:
            return "", False
        brand = getattr(parsed, "brand", "") or ""
        if brand in ("NON", "?", ""):
            return "", False
        return str(brand).strip(), True
    b = _fallback_brand_from_name(name)
    if b in ("NON", "?", ""):
        return "", False
    return b, bool(b)


def _norm_applicability(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in ("universal", "универсальный"):
        return "universal"
    return "fitment"


def _norm_generation_status(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s in GENERATION_STATUSES:
        return s
    return "new"


def _safe_int_year(v: Any) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def fetch_all_products(
    session: requests.Session,
    base_url: str,
    *,
    page_limit: int = 1000,
    max_products: int | None = None,
) -> list[dict[str, Any]]:
    """GET /entity/product?expand=attributes with offset pagination until a short page."""
    rows_out: list[dict[str, Any]] = []
    offset = 0
    while True:
        url = f"{base_url.rstrip('/')}/entity/product"
        params = {"expand": "attributes", "limit": page_limit, "offset": offset}
        r = session.get(url, params=params, timeout=120)
        if r.status_code != 200:
            print(f"MoySklad GET /entity/product failed: HTTP {r.status_code}")
            print(r.text[:4000])
            sys.exit(1)
        try:
            data = r.json()
        except ValueError as e:
            print(f"Invalid JSON from MoySklad: {e}")
            print(r.text[:4000])
            sys.exit(1)
        batch = data.get("rows")
        if batch is None:
            batch = []
        if not isinstance(batch, list):
            print(f"Unexpected 'rows' type: {type(batch).__name__}")
            sys.exit(1)
        for row in batch:
            if not isinstance(row, dict):
                continue
            rows_out.append(row)
            if max_products is not None and len(rows_out) >= max_products:
                return rows_out
        if len(batch) < page_limit:
            break
        offset += len(batch)
    return rows_out


def _product_row_for_hash(
    *,
    article: str,
    brand: str,
    part_type: str,
    side_axis: str,
    applicability_type: str,
    make: str,
    model: str,
    body: str,
    year_from: int,
    year_to: int,
    engine: str,
) -> dict[str, Any]:
    tk = "fitment_base" if applicability_type == "fitment" else "universal_base"
    tv = "v1"
    d: dict[str, Any] = {
        "brand": brand,
        "part_type": part_type,
        "article": article,
        "side_axis": side_axis,
        "cross_numbers": "",
        "template_key": tk,
        "template_version": tv,
        "applicability_type": applicability_type,
    }
    if applicability_type == "fitment":
        d["primary_make"] = make
        d["primary_model"] = model
        d["primary_body"] = body
        d["year_from"] = year_from
        d["year_to"] = year_to
        d["engine"] = engine
    return d


def _fitment_rows_for_hash(
    applicability_type: str,
    make: str,
    model: str,
    body: str,
    year_from: int,
    year_to: int,
    engine: str,
) -> list[dict[str, Any]]:
    if applicability_type != "fitment":
        return []
    if not (make.strip() and model.strip()):
        return []
    return [
        {
            "make": make.strip(),
            "model": model.strip(),
            "body": body or "",
            "year_from": year_from,
            "year_to": year_to,
            "engine": engine or "",
        }
    ]


def _compute_import_source_hash(
    *,
    article: str,
    brand: str,
    part_type: str,
    side_axis: str,
    applicability_type: str,
    make: str,
    model: str,
    body: str,
    year_from: int,
    year_to: int,
    engine: str,
) -> str:
    """Same canonical SHA-256 as the Streamlit app (``compute_source_hash``)."""
    prod = _product_row_for_hash(
        article=article,
        brand=brand,
        part_type=part_type,
        side_axis=side_axis,
        applicability_type=applicability_type,
        make=make,
        model=model,
        body=body,
        year_from=year_from,
        year_to=year_to,
        engine=engine,
    )
    rows = _fitment_rows_for_hash(
        applicability_type, make, model, body, year_from, year_to, engine
    )
    return compute_source_hash(prod, rows)


def run_import_hash_audit(rows: list[dict[str, Any]], id_to_key: dict[str, str]) -> int:
    """Compare remote snapshot hash with local ``source_hash`` (no writes)."""
    changed = 0
    with get_conn() as conn:
        for row in rows:
            ms_id = str(row.get("id") or "")
            if not ms_id:
                continue
            name = str(row.get("name") or "")
            article = str(row.get("article") or "")
            attrs = extract_attrs(row, id_to_key)
            brand = str(attrs.get("brand") or "").strip()
            part_type = str(attrs.get("part_type") or "").strip()
            make = str(attrs.get("make") or "").strip()
            model = str(attrs.get("model") or "").strip()
            body = str(attrs.get("body") or "").strip()
            side = str(attrs.get("side") or "").strip()
            engine = str(attrs.get("engine") or "").strip()
            year_from = _safe_int_year(attrs.get("year_from"))
            year_to = _safe_int_year(attrs.get("year_to"))
            app_type = _norm_applicability(str(attrs.get("applicability_type") or "fitment"))
            name_locked = int(attrs.get("name_locked") or 0)

            if not brand:
                fb, _used = _parse_brand_fallback(name)
                if fb:
                    brand = fb

            part_type_before = part_type
            brand_before = brand
            if _name_parser_parse is not None:
                parsed = _name_parser_parse(name)
                if parsed is not None and (parsed.category or "").strip():
                    if not (part_type_before or "").strip():
                        part_type = parsed.category.strip()
                    nb = (parsed.brand or "NON").strip() or "NON"
                    if (not (brand_before or "").strip() or (brand_before or "").strip() == "NON") and nb != "NON":
                        brand = nb

            if name_locked == 1:
                continue

            local_hash = _compute_import_source_hash(
                article=article,
                brand=brand,
                part_type=part_type,
                side_axis=side,
                applicability_type=app_type,
                make=make,
                model=model,
                body=body,
                year_from=year_from,
                year_to=year_to,
                engine=engine,
            )
            ex = conn.execute(
                "SELECT source_hash, name_locked FROM products WHERE ms_product_id = ?",
                (ms_id,),
            ).fetchone()
            if ex is None:
                continue
            if int(ex[1] or 0) == 1:
                continue
            if str(ex[0] or "") != local_hash:
                changed += 1
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Import MoySklad products into SQLite.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and parse only; no DB writes.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare MoySklad data with local source_hash (no DB writes).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Stop after processing N products (testing).",
    )
    args = parser.parse_args()

    _load_dotenv(_ROOT / ".env")
    id_to_key = load_attr_map(_ATTR_MAP_PATH)
    base_url, headers = _resolve_auth()

    session = requests.Session()
    session.headers.update(headers)

    max_fetch = args.limit
    rows = fetch_all_products(session, base_url, max_products=max_fetch)
    total = len(rows)

    if args.check:
        init_db()
        changed = run_import_hash_audit(rows, id_to_key)
        print(f"{changed} products changed in MoySklad since last import")
        return

    inserted = 0
    updated = 0
    skipped_locked = 0
    skipped_same_hash = 0
    brand_fallback_count = 0
    parsed_from_supplier = 0

    if not args.dry_run:
        init_db()

    for row in rows:
        ms_id = str(row.get("id") or "")
        name = str(row.get("name") or "")
        article = str(row.get("article") or "")
        ext = str(row.get("externalCode") or row.get("code") or ms_id or article or "unknown")

        attrs = extract_attrs(row, id_to_key)
        brand = str(attrs.get("brand") or "").strip()
        part_type = str(attrs.get("part_type") or "").strip()
        make = str(attrs.get("make") or "").strip()
        model = str(attrs.get("model") or "").strip()
        body = str(attrs.get("body") or "").strip()
        side = str(attrs.get("side") or "").strip()
        engine = str(attrs.get("engine") or "").strip()
        year_from = _safe_int_year(attrs.get("year_from"))
        year_to = _safe_int_year(attrs.get("year_to"))
        app_type = _norm_applicability(str(attrs.get("applicability_type") or "fitment"))
        gen_status = _norm_generation_status(str(attrs.get("generation_status") or "new"))
        name_locked = int(attrs.get("name_locked") or 0)

        if not brand:
            fb, used = _parse_brand_fallback(name)
            if fb:
                brand = fb
            if used:
                brand_fallback_count += 1

        part_type_before = part_type
        brand_before = brand
        if _name_parser_parse is not None:
            parsed = _name_parser_parse(name)
            if parsed is not None and (parsed.category or "").strip():
                applied = False
                if not (part_type_before or "").strip():
                    part_type = parsed.category.strip()
                    applied = True
                nb = (parsed.brand or "NON").strip() or "NON"
                if (not (brand_before or "").strip() or (brand_before or "").strip() == "NON") and nb != "NON":
                    brand = nb
                    applied = True
                if applied:
                    parsed_from_supplier += 1

        if not make:
            fit_tok = parse_fitment_token(name)
            if fit_tok:
                pair = resolve_make_from_model(fit_tok)
                if pair:
                    make, model = pair

        if name_locked == 1:
            skipped_locked += 1
            if args.dry_run:
                print(
                    json.dumps(
                        {"ms_product_id": ms_id, "skipped": "ms_name_locked", "name": name},
                        ensure_ascii=False,
                    )
                )
            continue

        local_hash = _compute_import_source_hash(
            article=article,
            brand=brand,
            part_type=part_type,
            side_axis=side,
            applicability_type=app_type,
            make=make,
            model=model,
            body=body,
            year_from=year_from,
            year_to=year_to,
            engine=engine,
        )

        if args.dry_run:
            preview = {
                "ms_product_id": ms_id,
                "supplier_raw_name": name,
                "article": article,
                "external_code": ext,
                "brand": brand,
                "part_type": part_type,
                "primary_make": make,
                "primary_model": model,
                "primary_body": body,
                "side_axis": side,
                "engine": engine,
                "year_from": year_from,
                "year_to": year_to,
                "applicability_type": app_type,
                "generation_status": gen_status,
                "name_locked": name_locked,
                "source_hash_computed": local_hash,
            }
            print(json.dumps(preview, ensure_ascii=False))
            continue

        old_hash = ""
        pid: int | None = None
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT id, source_hash, name_locked FROM products WHERE ms_product_id = ?",
                (ms_id,),
            )
            existing = cur.fetchone()

            if existing is not None:
                old_hash = str(existing[1] or "")
                db_locked = int(existing[2] or 0)
                if db_locked == 1:
                    skipped_locked += 1
                    continue
                if old_hash == local_hash:
                    skipped_same_hash += 1
                    continue

            template_key = "fitment_base" if app_type == "fitment" else "universal_base"
            template_version = "v1"

            existing_folder = ""
            if existing is not None:
                pf = conn.execute(
                    "SELECT product_folder FROM products WHERE ms_product_id = ?",
                    (ms_id,),
                ).fetchone()
                if pf is not None:
                    existing_folder = str(pf[0] or "").strip()

            resolved_folder: str | None = existing_folder or None
            if not resolved_folder:
                cur_f = conn.execute(
                    "SELECT ms_folder_path FROM part_type_folder_map "
                    "WHERE part_type = ?",
                    (part_type,),
                )
                row_f = cur_f.fetchone()
                resolved_folder = str(row_f[0]) if row_f and row_f[0] else None
            if not resolved_folder:
                resolved_folder = "Товары без категории"

            conn.execute(
                """
                INSERT INTO products (
                    ms_product_id, external_code, article, brand, part_type,
                    applicability_type, side_axis, supplier_raw_name,
                    generation_status, name_locked, source_hash,
                    template_key, template_version,
                    primary_make, primary_model, primary_body,
                    year_from, year_to, engine,
                    fitment_summary, product_folder
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ms_product_id) DO UPDATE SET
                    external_code = excluded.external_code,
                    article = excluded.article,
                    brand = excluded.brand,
                    part_type = excluded.part_type,
                    applicability_type = excluded.applicability_type,
                    side_axis = excluded.side_axis,
                    supplier_raw_name = excluded.supplier_raw_name,
                    generation_status = excluded.generation_status,
                    source_hash = excluded.source_hash,
                    template_key = excluded.template_key,
                    template_version = excluded.template_version,
                    primary_make = excluded.primary_make,
                    primary_model = excluded.primary_model,
                    primary_body = excluded.primary_body,
                    year_from = excluded.year_from,
                    year_to = excluded.year_to,
                    engine = excluded.engine,
                    fitment_summary = excluded.fitment_summary,
                    product_folder = COALESCE(
                        NULLIF(TRIM(products.product_folder), ''),
                        excluded.product_folder
                    )
                WHERE products.name_locked = 0
                  AND products.source_hash != excluded.source_hash
                """,
                (
                    ms_id,
                    ext,
                    article,
                    brand,
                    part_type,
                    app_type,
                    side or None,
                    name or None,
                    gen_status,
                    0,
                    local_hash,
                    template_key,
                    template_version,
                    make or None,
                    model or None,
                    body or None,
                    year_from if year_from else None,
                    year_to,
                    engine or None,
                    None,
                    resolved_folder,
                ),
            )

            cur2 = conn.execute(
                "SELECT id, source_hash, name_locked FROM products WHERE ms_product_id = ?",
                (ms_id,),
            )
            after = cur2.fetchone()
            if after is None:
                continue
            pid = int(after[0])
            new_hash = str(after[1] or "")
            existed_before = existing is not None
            if not existed_before:
                inserted += 1
            elif new_hash == local_hash and old_hash != local_hash:
                updated += 1
            elif new_hash == old_hash:
                skipped_same_hash += 1

            if app_type == "universal":
                delete_all_fitment(pid, conn)
            elif make and model:
                save_fitment(
                    pid,
                    [
                        FitmentRow(
                            product_id=pid,
                            make=make,
                            model=model,
                            body=body or None,
                            year_from=year_from if year_from else None,
                            year_to=year_to,
                            engine=engine or None,
                            sort_order=0,
                        )
                    ],
                    conn=conn,
                )
            else:
                delete_all_fitment(pid, conn)

    print(f"Fetched: {total}")
    print(f"Inserted: {inserted}")
    print(f"Updated:  {updated}")
    print(f"Skipped (locked): {skipped_locked}")
    print(f"Skipped (no change): {skipped_same_hash}")
    print(f"Brand fallback used: {brand_fallback_count}")
    print(f"Parsed from supplier_raw_name: {parsed_from_supplier}")


if __name__ == "__main__":
    main()
