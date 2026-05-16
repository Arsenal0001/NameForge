"""
One-time MoySklad custom attribute setup for NameForge.

Discovery (GET metadata), create missing attributes, emit ATTR_MAP with UUIDs.

Run from project root:
  python scripts/setup_ms_attributes.py --dry-run
  python scripts/setup_ms_attributes.py
  python scripts/setup_ms_attributes.py --patch-missing
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_BASE = "https://api.moysklad.ru/api/remap/1.2"

# Built-in MS fields (never POST); include in ATTR_MAP when present in metadata.
_BUILTIN_ATTRS: tuple[tuple[str, str, str | None], ...] = (
    ("Бренд", "brand", "string"),
    # NameForge expects plain text; MoySklad may use another type — warn only.
    ("Характеристики", "characteristics", "string"),
)

REQUIRED: tuple[tuple[str, str, str], ...] = (
    ("Тип детали", "string", "part_type"),
    ("Марка авто", "string", "make"),
    ("Модель авто", "string", "model"),
    ("Год от", "long", "year_from"),
    ("Год до", "long", "year_to"),
    ("Кузов", "string", "body"),
    ("Сторона", "string", "side"),
    ("Двигатель", "string", "engine"),
    ("Тип применимости", "string", "applicability_type"),
    ("Статус NF", "string", "generation_status"),
    ("Имя заблокировано NF", "boolean", "name_locked"),
    ("Хэш NF", "string", "source_hash"),
    ("Сгенерированное имя NF", "string", "generated_name"),
    ("Синхронизировано NF", "string", "synced_at"),
    ("Ошибка NF", "string", "error_message"),
)


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
    Return (base_url, headers) for MoySklad JSON API.

    Token: MS_TOKEN or MS_API_TOKEN (Bearer). Else MS_LOGIN + MS_PASSWORD (Basic).
    """
    token = (os.environ.get("MS_TOKEN") or os.environ.get("MS_API_TOKEN") or "").strip()
    login = (os.environ.get("MS_LOGIN") or "").strip()
    password = (os.environ.get("MS_PASSWORD") or "").strip()
    base = (os.environ.get("MS_BASE_URL") or _DEFAULT_BASE).rstrip("/")

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
        "  - MS_TOKEN (Bearer), or MS_API_TOKEN (same, used by the app), or\n"
        "  - MS_LOGIN and MS_PASSWORD (Basic).\n"
        "Optional: MS_BASE_URL (default: https://api.moysklad.ru/api/remap/1.2)\n"
        f"Expected file: {_ROOT / '.env'}"
    )
    sys.exit(1)


def fetch_all_attributes(session: requests.Session, base_url: str) -> dict[str, str]:
    """Returns {name: id} from dedicated attributes endpoint with pagination."""
    rows_out: list[dict[str, Any]] = []
    url: str | None = f"{base_url}/entity/product/metadata/attributes"
    while url:
        r = session.get(url, timeout=60)
        if not r.ok:
            print(f"{r.status_code}\n{r.text}")
            sys.exit(1)
        try:
            data = r.json()
        except ValueError:
            print(f"{r.status_code}\n{r.text}")
            sys.exit(1)
        if not isinstance(data, dict):
            print(f"{r.status_code}\n{r.text}")
            sys.exit(1)
        for attr in data.get("rows", []):
            if isinstance(attr, dict):
                rows_out.append(attr)
        meta = data.get("meta", {})
        if not isinstance(meta, dict):
            meta = {}
        offset = meta.get("offset", 0)
        limit = meta.get("limit", 25)
        size = meta.get("size", 0)
        url = (
            f"{base_url}/entity/product/metadata/attributes?offset={offset + limit}"
            if offset + limit < size
            else None
        )
    fetch_all_attributes._last_rows = rows_out  # type: ignore[attr-defined]
    return _existing_ids_from_attrs(rows_out)


def _build_existing_map(attrs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    m: dict[str, dict[str, Any]] = {}
    for a in attrs:
        name = a.get("name")
        aid = a.get("id")
        typ = a.get("type")
        req = a.get("required")
        if isinstance(name, str) and aid:
            m[name] = {"id": str(aid), "type": typ, "required": req}
    return m


def _existing_ids_from_attrs(attrs: list[dict[str, Any]]) -> dict[str, str]:
    """First GET: name → attribute UUID for all custom attributes returned."""
    out: dict[str, str] = {}
    for a in attrs:
        name = a.get("name")
        aid = a.get("id")
        if isinstance(name, str) and aid:
            out[name] = str(aid)
    return out


def _post_attribute(
    session: requests.Session,
    base: str,
    *,
    name: str,
    ms_type: str,
) -> str:
    url = f"{base}/entity/product/metadata/attributes"
    body = {"name": name, "type": ms_type, "required": False}
    r = session.post(url, json=body, timeout=60)
    if r.status_code not in (200, 201):
        print(
            f"POST attribute failed HTTP {r.status_code} for {name!r}\n{r.text}",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        created = r.json()
    except ValueError:
        print(f"POST returned non-JSON body:\n{r.text}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(created, dict) or not created.get("id"):
        print(f"POST response missing id:\n{r.text}", file=sys.stderr)
        sys.exit(1)
    time.sleep(0.2)
    return str(created["id"])


def _attr_map_key_order() -> list[str]:
    names: list[str] = []
    for n, _, _ in _BUILTIN_ATTRS:
        if n == "Характеристики":
            continue
        names.append(n)
    names.extend(n for n, _, _ in REQUIRED)
    names.append("Характеристики")
    return names


def _print_attr_map_python(m: dict[str, dict[str, str]], *, key_order: list[str]) -> None:
    width = max(len(k) for k in key_order) if key_order else 0
    print("\nATTR_MAP = {")
    for name in key_order:
        if name not in m:
            continue
        entry = m[name]
        pad = " " * (width - len(name))
        print(f'    "{name}":{pad} {{"id": "{entry["id"]}", "key": "{entry["key"]}"}},')
    print("}")


def _ensure_utf8_stdio() -> None:
    """Best-effort UTF-8 for stdout/stderr (e.g. Cyrillic on Windows consoles)."""
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if not callable(reconf):
            continue
        try:
            reconf(encoding="utf-8")
        except (ValueError, OSError):
            pass


def _run_patch_missing(session: requests.Session, base: str) -> None:
    """Fill empty ids in config/attr_map.json from GET .../metadata/attributes."""
    path = _ROOT / "config" / "attr_map.json"
    if not path.is_file():
        print(f"Missing {path}: create it with a normal setup run first.", file=sys.stderr)
        sys.exit(1)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        print(f"Cannot read {path}: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(raw, dict):
        print(f"Expected object in {path}, got {type(raw).__name__}", file=sys.stderr)
        sys.exit(1)

    def _canonical_key(attr_name: str) -> str:
        for n, k, _ in _BUILTIN_ATTRS:
            if n == attr_name:
                return k
        for n, _, k in REQUIRED:
            if n == attr_name:
                return k
        return ""

    key_order = _attr_map_key_order()
    attr_map: dict[str, dict[str, str]] = {}
    for name in key_order:
        entry = raw.get(name)
        if isinstance(entry, dict):
            kid = str(entry.get("key") or "") or _canonical_key(name)
            attr_map[name] = {
                "id": str(entry.get("id") or ""),
                "key": kid,
            }
        else:
            print(f"WARNING: entry for {name!r} missing or invalid in {path}", file=sys.stderr)
            attr_map[name] = {"id": "", "key": _canonical_key(name)}

    by_name = fetch_all_attributes(session, base)

    print(
        f"Quick check (--patch-missing): fetched {len(by_name)} attribute(s) "
        f"from {base}/entity/product/metadata/attributes"
    )

    for name in key_order:
        entry = attr_map[name]
        if entry.get("id"):
            continue
        fid = by_name.get(name)
        if fid:
            entry["id"] = fid
            print(f"PATCHED: '{name}' → {fid}")

    ordered_map = {k: attr_map[k] for k in key_order}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ordered_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nWrote {path.relative_to(_ROOT)} ({len(ordered_map)} entries)")


def main() -> None:
    _ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Setup MoySklad product custom attributes.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions only; no POST; do not write config/attr_map.json",
    )
    parser.add_argument(
        "--patch-missing",
        action="store_true",
        help="GET .../metadata/attributes and fill empty ids in config/attr_map.json by name",
    )
    args = parser.parse_args()
    dry_run = args.dry_run
    patch_missing = args.patch_missing

    if patch_missing and dry_run:
        print("Cannot combine --patch-missing with --dry-run.", file=sys.stderr)
        sys.exit(2)

    _load_dotenv(_ROOT / ".env")
    base, headers = _resolve_auth()
    session = requests.Session()
    session.headers.update(headers)

    if patch_missing:
        _run_patch_missing(session, base)
        return

    existing_ids = fetch_all_attributes(session, base)
    attrs0 = getattr(fetch_all_attributes, "_last_rows", [])
    existing = _build_existing_map(attrs0)
    created_ids: dict[str, str] = {}
    builtins_missing: list[str] = []

    print(
        f"Quick check: fetched {len(existing_ids)} attribute(s) "
        f"from {base}/entity/product/metadata/attributes"
    )

    # Built-ins: report only, never POST
    for name, _key, expected_type in _BUILTIN_ATTRS:
        if name not in existing:
            builtins_missing.append(name)
            continue
        info = existing[name]
        typ = info.get("type")
        print(f"EXISTS: '{name}' → {info['id']} (type={typ!r})")
        if expected_type is not None and typ != expected_type:
            print(
                f"WARNING: '{name}' exists but type is {typ!r}, expected {expected_type!r} — "
                "immutable in MoySklad; do not recreate"
            )

    for name, ms_type, _key in REQUIRED:
        if name not in existing:
            if dry_run:
                print(f"WOULD CREATE: '{name}' (type={ms_type})")
            else:
                new_id = _post_attribute(session, base, name=name, ms_type=ms_type)
                created_ids[name] = new_id
                print(f"CREATED: '{name}' → {new_id}")
            continue

        info = existing[name]
        cur_type = info.get("type")
        if cur_type != ms_type:
            print(
                f"WARNING: '{name}' exists but type is {cur_type!r}, expected {ms_type!r} — SKIP "
                "(types are immutable; never delete)"
            )
        else:
            print(f"EXISTS: '{name}' → {info['id']}")

    if dry_run:
        print("\n(dry-run: skipping ATTR_MAP write to config/attr_map.json)")
        return

    known_ids: dict[str, str] = {**existing_ids, **created_ids}

    attr_map: dict[str, dict[str, str]] = {}
    for name, key, _exp in _BUILTIN_ATTRS:
        aid = known_ids.get(name, "")
        attr_map[name] = {"id": aid, "key": key}
        if aid == "" and name not in builtins_missing:
            print(f"WARNING: '{name}' id unknown — check MoySklad UI")

    for name, _ms_type, key in REQUIRED:
        aid = known_ids.get(name, "")
        attr_map[name] = {"id": aid, "key": key}
        if aid == "":
            print(f"WARNING: '{name}' id unknown — check MoySklad UI")

    key_order = _attr_map_key_order()
    ordered_map = {k: attr_map[k] for k in key_order}

    out_path = _ROOT / "config" / "attr_map.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(ordered_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    _print_attr_map_python(ordered_map, key_order=key_order)
    print(f"\nWrote {out_path.relative_to(_ROOT)} ({len(ordered_map)} entries)")

    for bn in builtins_missing:
        print(
            f"\nACTION REQUIRED: Create '{bn}' manually in MoySklad UI, then run:\n"
            f"  python scripts/setup_ms_attributes.py --patch-missing\n"
            "to update config/attr_map.json with its UUID."
        )


if __name__ == "__main__":
    main()
