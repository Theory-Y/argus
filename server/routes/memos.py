"""Memo generation: submit, poll, download.

POST   /api/v1/memos                  → 202 {job_id}
GET    /api/v1/memos/{job_id}         → status/progress
GET    /api/v1/memos/{job_id}/download?format=pdf → file (local) or redirect (S3)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, authenticate, get_auth_provider
from ..db.models import Job
from ..db.session import get_db
from ..jobs.queue import get_queue
from ..jobs.tasks import generate_memo
from ..schemas import MemoCreate, MemoFormat, MemoJob
from ..storage import get_storage

router = APIRouter(prefix="/api/v1", tags=["memos"])


def _job_to_schema(job: Job) -> MemoJob:
    return MemoJob(
        job_id=job.id,
        ticker=job.ticker,
        status=job.status.value,
        progress=job.progress,
        error=job.error,
        formats=list(job.artifacts.keys()) if job.artifacts else [],
    )


def _load_owned_job(job_id: str, principal: Principal, db: Session) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    # In SaaS mode, never expose another user's job. License mode (id None) is open.
    if principal.id is not None and job.user_id != principal.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/memos", status_code=202, response_model=MemoJob)
def create_memo(
    req: MemoCreate,
    principal: Principal = Depends(authenticate),
    db: Session = Depends(get_db),
) -> MemoJob:
    get_auth_provider().check_quota(principal, db)

    job = Job(user_id=principal.id, ticker=req.ticker.upper().strip(), fmt=req.format)
    db.add(job)
    db.commit()
    db.refresh(job)

    get_queue().enqueue(generate_memo, job.id)
    return _job_to_schema(job)


@router.get("/memos", response_model=list[MemoJob])
def list_memos(
    principal: Principal = Depends(authenticate),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, le=200),
) -> list[MemoJob]:
    q = select(Job).order_by(Job.created_at.desc()).limit(limit)
    # SaaS: only the caller's jobs. License (id None): all jobs on this instance.
    if principal.id is not None:
        q = q.where(Job.user_id == principal.id)
    return [_job_to_schema(j) for j in db.scalars(q).all()]


@router.get("/memos/{job_id}", response_model=MemoJob)
def get_memo(
    job_id: str,
    principal: Principal = Depends(authenticate),
    db: Session = Depends(get_db),
) -> MemoJob:
    return _job_to_schema(_load_owned_job(job_id, principal, db))


@router.get("/memos/{job_id}/download")
def download_memo(
    job_id: str,
    format: MemoFormat = Query(default="pdf"),
    principal: Principal = Depends(authenticate),
    db: Session = Depends(get_db),
):
    job = _load_owned_job(job_id, principal, db)
    if job.status.value != "complete" or not job.artifacts:
        raise HTTPException(status_code=409, detail="Memo not ready")

    key = job.artifacts.get(format)
    if not key:
        available = ", ".join(job.artifacts.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Format '{format}' not available. Produced: {available}",
        )

    storage = get_storage()
    url = storage.presigned_url(key)
    if url:
        return RedirectResponse(url)

    path = storage.resolve_path(key)
    if not path:
        raise HTTPException(status_code=410, detail="Artifact no longer available")
    filename = f"TheoryY_Memo_{job.ticker.upper()}.{format}"
    return FileResponse(path, filename=filename)
