from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.mailbox import SyncJob
from app.models.user import User
from app.services.gmail_sync import job_payload, owned_account
from app.services.sync_jobs import submit_sync

router = APIRouter(prefix="/accounts", tags=["sync"])


class SyncRequest(BaseModel):
    reconcile: bool = False


class SyncJobResponse(BaseModel):
    id: int
    account_id: int
    kind: Literal["initial", "incremental", "reconcile"]
    status: Literal["queued", "running", "succeeded", "failed"]
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    available_at: datetime


@router.post("/{account_id}/sync", response_model=SyncJobResponse, status_code=202)
def sync_account(account_id: int, request: SyncRequest | None = None,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return submit_sync(db, user.id, account_id, reconcile=bool(request and request.reconcile))


@router.get("/{account_id}/sync-jobs", response_model=list[SyncJobResponse])
def recent_jobs(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned_account(db, user.id, account_id)
    return [job_payload(job) for job in db.query(SyncJob).filter_by(account_id=account_id).order_by(SyncJob.id.desc()).limit(20)]


@router.get("/{account_id}/sync-jobs/{job_id}", response_model=SyncJobResponse)
def get_job(account_id: int, job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned_account(db, user.id, account_id)
    job = db.query(SyncJob).filter_by(account_id=account_id, id=job_id).first()
    if job is None:
        raise HTTPException(404, "Sync job not found")
    return job_payload(job)
