"""Idempotent insert of per-matrix ``templates`` rows (fitment / universal)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.template import Template
from app.services.naming_matrices import (
    LOGICAL_MATRIX_IDS,
    _PATTERN_FITMENT,
    _PATTERN_UNIVERSAL,
    physical_template_key,
)


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def ensure_matrix_templates(session: Session) -> int:
    """Insert missing template rows for all logical matrices. Returns number of rows added."""
    now = _iso_now()
    added = 0
    for logical in sorted(LOGICAL_MATRIX_IDS):
        for appl, pattern in (
            ("fitment", _PATTERN_FITMENT),
            ("universal", _PATTERN_UNIVERSAL),
        ):
            tk = physical_template_key(logical, appl)  # type: ignore[arg-type]
            exists = session.scalar(
                select(Template.id).where(
                    Template.template_key == tk,
                    Template.version == "v1",
                )
            )
            if exists is not None:
                continue
            session.add(
                Template(
                    template_key=tk,
                    version="v1",
                    applicability_type=appl,
                    name_pattern=pattern,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                    part_type_pattern=None,
                    part_type_trigger=None,
                )
            )
            added += 1
    return added
