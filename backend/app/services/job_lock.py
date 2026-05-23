"""In-memory mutex for long-running dashboard jobs (single-process API)."""

from __future__ import annotations

import threading
from enum import StrEnum


class JobKind(StrEnum):
    SYNC_FROM_ODOO = "sync_from_odoo"
    ENRICH = "enrich"
    PUSH_TO_ODOO = "push_to_odoo"


_running: set[JobKind] = set()
_guard = threading.Lock()


def try_acquire(kind: JobKind) -> bool:
    """Return True when the job slot was reserved."""
    with _guard:
        if kind in _running:
            return False
        _running.add(kind)
        return True


def release(kind: JobKind) -> None:
    with _guard:
        _running.discard(kind)


def is_running(kind: JobKind) -> bool:
    with _guard:
        return kind in _running
