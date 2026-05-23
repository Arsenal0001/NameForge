"""In-memory progress tracking for long-running dashboard jobs."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from app.services.job_lock import JobKind

PROGRESS_UPDATE_MIN_DELTA = 500


class JobRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobProgressRecord:
    job_type: JobKind
    status: JobRunStatus
    processed_items: int = 0
    total_items: int = 0
    error_message: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None

    @property
    def progress_percent(self) -> float:
        if self.total_items <= 0:
            if self.status is JobRunStatus.COMPLETED:
                return 100.0
            return 0.0
        return min(100.0, round(100.0 * self.processed_items / self.total_items, 1))


class JobProgressManager:
    """Thread-safe tracker for one active or last terminal run per job kind."""

    def __init__(self) -> None:
        self._records: dict[JobKind, JobProgressRecord] = {}
        self._guard = threading.Lock()

    def start(self, kind: JobKind, *, total_items: int = 0) -> None:
        with self._guard:
            self._records[kind] = JobProgressRecord(
                job_type=kind,
                status=JobRunStatus.RUNNING,
                total_items=max(0, total_items),
            )

    def set_total(self, kind: JobKind, total_items: int) -> None:
        with self._guard:
            record = self._records.get(kind)
            if record is None:
                return
            record.total_items = max(0, total_items)

    def update(
        self,
        kind: JobKind,
        processed_items: int,
        *,
        total_items: int | None = None,
        force: bool = False,
        min_delta: int = PROGRESS_UPDATE_MIN_DELTA,
    ) -> None:
        with self._guard:
            record = self._records.get(kind)
            if record is None or record.status is not JobRunStatus.RUNNING:
                return
            if total_items is not None:
                record.total_items = max(0, total_items)
            processed_items = max(0, processed_items)
            if not force and record.total_items > 0:
                delta = processed_items - record.processed_items
                at_boundary = processed_items in {0, record.total_items}
                if delta < min_delta and not at_boundary:
                    return
            record.processed_items = processed_items

    def complete(
        self,
        kind: JobKind,
        *,
        processed_items: int | None = None,
    ) -> None:
        with self._guard:
            record = self._records.get(kind)
            if record is None:
                return
            if processed_items is not None:
                record.processed_items = max(0, processed_items)
            elif record.total_items > 0:
                record.processed_items = record.total_items
            record.status = JobRunStatus.COMPLETED
            record.error_message = None
            record.finished_at = datetime.now(UTC)

    def fail(self, kind: JobKind, error_message: str) -> None:
        with self._guard:
            record = self._records.get(kind)
            if record is None:
                self._records[kind] = JobProgressRecord(
                    job_type=kind,
                    status=JobRunStatus.FAILED,
                    error_message=error_message,
                    finished_at=datetime.now(UTC),
                )
                return
            record.status = JobRunStatus.FAILED
            record.error_message = error_message
            record.finished_at = datetime.now(UTC)

    def list_active_and_recent(self) -> list[JobProgressRecord]:
        with self._guard:
            return sorted(
                self._records.values(),
                key=lambda item: item.started_at,
                reverse=True,
            )


job_progress = JobProgressManager()
