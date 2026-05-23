"""Dashboard ETL job triggers (async background tasks)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.schemas.jobs import ActiveJobsResponse, JobAcceptedResponse, JobProgressItem
from app.services.catalog_jsonl_enrichment import DEFAULT_JSONL
from app.services.job_lock import JobKind, release, try_acquire
from app.services.job_progress import job_progress
from app.services.job_tasks import (
    run_enrich_job,
    run_push_to_odoo_job,
    run_sync_from_odoo_job,
)
from app.services.odoo_client import OdooClient, OdooClientError

router = APIRouter(prefix="/jobs", tags=["jobs"])

_JOB_RUNNING_DETAIL = "Job is already running"


@router.get("/active", response_model=ActiveJobsResponse)
def list_active_jobs() -> ActiveJobsResponse:
    """Return running jobs and the latest terminal state per job kind."""
    jobs = [
        JobProgressItem(
            job_type=str(record.job_type),
            status=record.status.value,
            processed_items=record.processed_items,
            total_items=record.total_items,
            progress_percent=record.progress_percent,
            error_message=record.error_message,
            started_at=record.started_at.isoformat() if record.started_at else None,
            finished_at=record.finished_at.isoformat() if record.finished_at else None,
        )
        for record in job_progress.list_active_and_recent()
    ]
    return ActiveJobsResponse(jobs=jobs)


def _accept_or_conflict(kind: JobKind) -> None:
    if not try_acquire(kind):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_JOB_RUNNING_DETAIL,
        )


def _preflight_odoo() -> None:
    try:
        OdooClient()
    except OdooClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/sync-from-odoo",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAcceptedResponse,
)
def trigger_sync_from_odoo(
    background_tasks: BackgroundTasks,
) -> JobAcceptedResponse:
    """Pull Odoo ``product.template`` rows into the local ``products`` cache."""
    _accept_or_conflict(JobKind.SYNC_FROM_ODOO)
    try:
        _preflight_odoo()
    except HTTPException:
        release(JobKind.SYNC_FROM_ODOO)
        raise

    background_tasks.add_task(run_sync_from_odoo_job)
    return JobAcceptedResponse(
        job=JobKind.SYNC_FROM_ODOO,
        message="Odoo catalog import queued",
    )


@router.post(
    "/enrich",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAcceptedResponse,
)
def trigger_enrich(background_tasks: BackgroundTasks) -> JobAcceptedResponse:
    """Enrich local products from ``odoo_master_catalog.jsonl`` (apply mode)."""
    _accept_or_conflict(JobKind.ENRICH)
    if not DEFAULT_JSONL.is_file():
        release(JobKind.ENRICH)
        raise HTTPException(
            status_code=400,
            detail=f"JSONL not found: {DEFAULT_JSONL}",
        )

    background_tasks.add_task(run_enrich_job)
    return JobAcceptedResponse(
        job=JobKind.ENRICH,
        message="JSONL enrichment queued",
    )


@router.post(
    "/push-to-odoo",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobAcceptedResponse,
)
def trigger_push_to_odoo(
    background_tasks: BackgroundTasks,
) -> JobAcceptedResponse:
    """Mass-push generated names to Odoo via SyncService (respects DRY_RUN)."""
    _accept_or_conflict(JobKind.PUSH_TO_ODOO)
    try:
        _preflight_odoo()
    except HTTPException:
        release(JobKind.PUSH_TO_ODOO)
        raise

    background_tasks.add_task(run_push_to_odoo_job)
    return JobAcceptedResponse(
        job=JobKind.PUSH_TO_ODOO,
        message="Mass Odoo push queued",
    )
