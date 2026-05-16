"""
Resolve a MoySklad folder path for a given ``part_type``.

Lookup strategy (active rows only, highest priority first):

1. Exact (case-insensitive via ``casefold``) match against ``part_type_pattern``.
2. Glob/fnmatch fallback (e.g. ``Амортизатор*``) against the same column.
3. ``None`` if nothing matches.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from typing import Iterable

from .db import get_conn

_SELECT_ACTIVE = """
    SELECT part_type_pattern, ms_folder_path, priority
    FROM category_mapping
    WHERE is_active = 1
    ORDER BY priority DESC, id ASC
"""


def _iter_rules() -> Iterable[tuple[str, str, int]]:
    with get_conn() as conn:
        for row in conn.execute(_SELECT_ACTIVE).fetchall():
            pattern = str(row[0] or "").strip()
            folder = str(row[1] or "").strip()
            try:
                priority = int(row[2] or 0)
            except (TypeError, ValueError):
                priority = 0
            if pattern and folder:
                yield pattern, folder, priority


def resolve_folder(part_type: str) -> str | None:
    """
    Find ``ms_folder_path`` for ``part_type``.

    Exact (case-insensitive) match wins over glob; within each group, higher
    ``priority`` wins; ties broken by insertion order.
    """
    needle = (part_type or "").strip()
    if not needle:
        return None

    needle_cf = needle.casefold()
    rules = list(_iter_rules())

    for pattern, folder, _ in rules:
        if pattern.casefold() == needle_cf:
            return folder

    for pattern, folder, _ in rules:
        if any(ch in pattern for ch in ("*", "?", "[")) and fnmatchcase(
            needle_cf, pattern.casefold()
        ):
            return folder

    return None
