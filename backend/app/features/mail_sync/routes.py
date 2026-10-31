from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.features.mailbox.models import SyncJob
from app.features.google_login.user import User
from app.features.mail_sync.service import job_payload, owned_account
from app.features.mail_sync.jobs import submit_sync

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
    messages_seen: int = 0
    messages_inserted: int = 0
    messages_updated: int = 0


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


class HistoricalRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=64)
    label: str | None = Field(default=None, max_length=128)


@router.post("/{account_id}/sync/historical", status_code=202)
def historical_sync(account_id: int, request: HistoricalRequest,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.features.mail_sync.historical import request_page
    return request_page(db, user.id, account_id, session_id=request.session_id, label=request.label)


@router.get("/{account_id}/sync/sessions/{session_id}")
def historical_status(account_id: int, session_id: str,
                      user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.features.mail_sync.historical import get_session, payload
    return payload(get_session(db, user.id, account_id, session_id))


class SyncSettings(BaseModel):
    initial_sync_days: int = Field(ge=1, le=365)


@router.patch("/{account_id}/sync/settings")
def sync_settings(account_id: int, request: SyncSettings,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = owned_account(db, user.id, account_id, lock=True)
    account.initial_sync_days = request.initial_sync_days
    db.commit()
    return {"initial_sync_days": account.initial_sync_days}


@router.get("/{account_id}/sync/status")
def sync_status(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    account = owned_account(db, user.id, account_id)
    return {"initial_sync_completed": account.mail_import_complete,
            "initial_sync_days": account.initial_sync_days, "last_synced_at": account.last_synced_at,
            "requires_reauth": account.requires_reauth, "sync_paused": account.sync_paused}


@router.get("/{account_id}/diagnostics")
def diagnostics(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.features.mail_sync.diagnostics import snapshot
    return snapshot(db, user.id, account_id)


@router.post("/{account_id}/sync/initial", status_code=202)
@router.post("/{account_id}/sync/incremental", status_code=202)
def start_sync(account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return submit_sync(db, user.id, account_id)


@router.get("/{account_id}/sync/jobs/{job_id}", response_model=SyncJobResponse)
def job_status(account_id: int, job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_job(account_id, job_id, user, db)
