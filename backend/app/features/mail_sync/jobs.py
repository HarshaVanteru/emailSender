"""Database outbox, leased attempts, and retry policy for mailbox reads only."""
import json
import random
import secrets
from datetime import timedelta

from billiard.exceptions import SoftTimeLimitExceeded
from fastapi import HTTPException
from google.auth.exceptions import TransportError
from googleapiclient.errors import HttpError
from redis.exceptions import RedisError
from requests.exceptions import RequestException
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core import config
from app.core.database import SessionLocal
from app.features.google_login.models import ConnectedAccount
from app.features.mailbox.models import AuditLog, SyncJob
from app.features.google_login.accounts import credentials_for_account
from app.integrations.gmail.client import gmail_service
from app.features.mail_sync.service import SyncFailure, apply_sync, check_read_access, job_payload, owned_account, request_guard, utcnow
from app.workers.celery_app import publish_job
from app.workers.rate_limit import GmailRateLimiter


def enqueue_sync(db, user_id, account_id, reconcile=False, *, scheduled=False):
    if scheduled:
        # Recheck eligibility under the account lock: a previous scan can be stale.
        try:
            account = owned_account(db, user_id, account_id, lock=True)
        except OperationalError:
            db.rollback()
            return None
        if (account.sync_paused or account.requires_reauth or not account.encrypted_credentials
                or (account.next_sync_at and account.next_sync_at > utcnow())):
            db.rollback()
            return None
        try:
            check_read_access(account)
        except HTTPException:
            account.next_sync_at = utcnow() + timedelta(seconds=config.SYNC_INTERVAL_SECONDS)
            db.commit()
            return None
        reconcile = bool(account.history_id and (account.next_reconcile_at is None or account.next_reconcile_at <= utcnow()))
    account = owned_account(db, user_id, account_id)
    check_read_access(account)
    existing = db.query(SyncJob).filter_by(active_account_id=account_id).first()
    if existing:
        if scheduled:
            db.rollback()
            return None
        if reconcile and existing.kind != "reconcile":
            if existing.status == "running":
                raise HTTPException(409, {"message": "A sync is running. Retry reconciliation after it finishes.", "job_id": existing.id})
            # Do not change an attempt that is already executing.
            changed = db.query(SyncJob).filter_by(id=existing.id, status="queued").update(
                {"kind": "reconcile"}, synchronize_session=False)
            db.commit()
            if not changed:
                raise HTTPException(409, {"message": "A sync is running. Retry reconciliation after it finishes.", "job_id": existing.id})
            db.refresh(existing)
        return existing
    try:
        account = owned_account(db, user_id, account_id, lock=True)
        check_read_access(account)
        now = utcnow()
        job = SyncJob(account_id=account_id, active_account_id=account_id,
                      kind="reconcile" if reconcile else "incremental" if account.history_id else "initial",
                      status="queued", attempts=0, available_at=now, dispatch_after=now)
        db.add(job)
        account.sync_paused = False  # An explicit manual retry resumes a paused account.
        account.next_sync_at = now + timedelta(seconds=config.SYNC_INTERVAL_SECONDS)
        db.commit()
        return job
    except IntegrityError:
        db.rollback()
        # The unique active-account key resolves simultaneous submissions.
        existing = db.query(SyncJob).filter_by(active_account_id=account_id).first()
        if existing:
            if reconcile and existing.kind != "reconcile" and not scheduled:
                return enqueue_sync(db, user_id, account_id, reconcile=True)
            return existing
        raise
    except OperationalError:
        db.rollback()
        raise HTTPException(409, "The account is busy. Try again shortly.") from None


def dispatch_job(db, job_id, publisher=publish_job):
    """Commit-before-publish outbox. Republish is safe because claims deduplicate."""
    job = db.query(SyncJob).filter_by(id=job_id, status="queued").populate_existing().with_for_update(skip_locked=True).first()
    now = utcnow()
    if job is None or job.available_at > now or (job.dispatch_after and job.dispatch_after > now):
        db.rollback()
        return True
    try:
        publisher(job.id)
    except Exception:
        job.error_code = "queue_unavailable"
        job.dispatch_after = now + timedelta(seconds=30)
        db.commit()
        return False
    job.dispatch_after = now + timedelta(seconds=60)
    if job.error_code == "queue_unavailable":
        job.error_code = None
    db.commit()
    return True


def submit_sync(db, user_id, account_id, reconcile=False):
    job = enqueue_sync(db, user_id, account_id, reconcile)
    job_id = job.id
    if not dispatch_job(db, job_id):
        raise HTTPException(503, {"message": "Sync is saved, but the queue is unavailable. It will be delivered when service recovers.",
                                  "job_id": job_id, "accepted": True, "error_code": "queue_unavailable"})
    db.expire_all()
    return job_payload(db.get(SyncJob, job_id))


def claim_job(db, job_id):
    snapshot = db.get(SyncJob, job_id)
    if snapshot is None or snapshot.status != "queued" or snapshot.available_at > utcnow():
        db.rollback()
        return None
    # All paths that lock both rows use account -> job order.
    account = db.query(ConnectedAccount).filter_by(id=snapshot.account_id).with_for_update(nowait=True).first()
    job = db.query(SyncJob).filter_by(id=job_id).populate_existing().with_for_update(nowait=True).one()
    if job.status != "queued" or job.available_at > utcnow() or job.active_account_id != account.id:
        db.rollback()
        return None
    if job.attempts >= config.SYNC_MAX_ATTEMPTS:
        finish_attempt(db, account, job, "attempts_exhausted", retryable=False)
        db.commit()
        return None
    now = utcnow()
    job.status, job.started_at, job.finished_at = "running", now, None
    job.attempts += 1
    job.lease_token = secrets.token_hex(24)
    job.lease_expires_at = now + timedelta(seconds=config.SYNC_LEASE_SECONDS)
    claim = (account.user_id, account.id, job.lease_token)
    db.commit()
    return claim


def classify_failure(exc):
    if isinstance(exc, SoftTimeLimitExceeded):
        return "worker_time_limit", True
    if isinstance(exc, RedisError):
        return "queue_unavailable", True
    if isinstance(exc, (TransportError, RequestException, TimeoutError, OSError)):
        return "gmail_transport_error", True
    if isinstance(exc, OperationalError):
        return "sync_database_unavailable", True
    if isinstance(exc, HttpError):
        status = exc.resp.status
        reasons = set()
        try:
            reasons = {item.get("reason") for item in json.loads(exc.content).get("error", {}).get("errors", [])}
        except (ValueError, AttributeError, TypeError):
            pass
        if status == 429 or (status == 403 and reasons & {"rateLimitExceeded", "userRateLimitExceeded", "backendError"}):
            return "gmail_rate_limited", True
        return f"gmail_http_{status}", 500 <= status < 600
    if isinstance(exc, HTTPException):
        return "connection_unavailable", 500 <= exc.status_code < 600
    if isinstance(exc, SyncFailure):
        return exc.code, False
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return "invalid_gmail_payload", False
    return "sync_failed", False


def finish_attempt(db, account, job, code, retryable):
    now = utcnow()
    job.error_code = code
    job.lease_token = job.lease_expires_at = None
    if retryable and job.attempts < config.SYNC_MAX_ATTEMPTS:
        delay = random.uniform(0.5, 1.0) * min(300, 15 * 2 ** max(0, job.attempts - 1))
        job.status, job.finished_at = "queued", None
        job.available_at = now + timedelta(seconds=delay)
        job.dispatch_after = job.available_at
    else:
        job.status, job.finished_at, job.active_account_id = "failed", now, None
        account.sync_paused = True
    db.add(AuditLog(user_id=account.user_id, account_id=account.id, action="mailbox.sync",
                    resource_type="sync_job", resource_id=str(job.id), outcome="retry" if job.status == "queued" else "failure"))


def record_failure(db, job_id, token, code, retryable):
    snapshot = db.get(SyncJob, job_id)
    if snapshot is None:
        return
    account = db.query(ConnectedAccount).filter_by(id=snapshot.account_id).with_for_update().one()
    job = db.query(SyncJob).filter_by(id=job_id).populate_existing().with_for_update().one()
    # A delayed, recovered worker must never overwrite a newer attempt.
    if job.status != "running" or job.lease_token != token:
        db.rollback()
        return
    finish_attempt(db, account, job, code, retryable)
    db.commit()


def process_job(job_id, session_factory=SessionLocal, service_factory=None, limiter=None):
    with session_factory() as db:
        try:
            claim = claim_job(db, job_id)
        except OperationalError:
            db.rollback()  # Outbox will redeliver an unclaimed queued job.
            return
        if claim is None:
            return
        user_id, account_id, token = claim
        try:
            if service_factory is None:
                credentials = credentials_for_account(db, user_id, account_id)
                service = gmail_service.get_gmail_service(credentials.to_json())
            else:
                service = service_factory()
            account = owned_account(db, user_id, account_id, lock=True)
            check_read_access(account)
            job = db.query(SyncJob).filter_by(id=job_id).populate_existing().with_for_update().one()
            if job.status != "running" or job.lease_token != token:
                db.rollback()
                return
            if job.lease_expires_at <= utcnow():
                raise SoftTimeLimitExceeded()
            gate = limiter if limiter is not None else GmailRateLimiter()
            # The job and account locks remain held through the cache commit.
            # Recovery uses SKIP LOCKED and cannot reclaim a live transaction.
            with request_guard(lambda: gate.wait(account_id)):
                job.kind = apply_sync(db, account, service, reconcile=job.kind == "reconcile")
            now = utcnow()
            job.status, job.finished_at, job.error_code = "succeeded", now, None
            job.active_account_id = job.lease_token = job.lease_expires_at = None
            account.next_sync_at = now + timedelta(seconds=config.SYNC_INTERVAL_SECONDS)
            if job.kind in ("initial", "reconcile"):
                account.next_reconcile_at = now + timedelta(seconds=config.SYNC_RECONCILE_SECONDS)
            account.sync_paused = False
            db.add(AuditLog(user_id=user_id, account_id=account_id, action="mailbox.sync",
                            resource_type="sync_job", resource_id=str(job_id), outcome="success"))
            db.commit()
        except Exception as exc:
            db.rollback()
            code, retryable = classify_failure(exc)
            record_failure(db, job_id, token, code, retryable)


def recover_expired(db):
    ids = [row[0] for row in db.query(SyncJob.id).filter(
        SyncJob.status == "running", SyncJob.lease_expires_at <= utcnow()).limit(100)]
    db.rollback()
    for job_id in ids:
        try:
            snapshot = db.get(SyncJob, job_id)
            account = db.query(ConnectedAccount).filter_by(id=snapshot.account_id).with_for_update(nowait=True).one()
            job = db.query(SyncJob).filter_by(id=job_id, status="running").filter(
                SyncJob.lease_expires_at <= utcnow()).populate_existing().with_for_update(skip_locked=True).first()
            if job is not None:
                finish_attempt(db, account, job, "worker_lost", retryable=True)
                db.commit()
            else:
                db.rollback()
        except OperationalError:
            db.rollback()  # An active worker owns the account/cache transaction.


def maintenance(session_factory=SessionLocal, publisher=publish_job):
    with session_factory() as db:
        recover_expired(db)
        active = db.query(SyncJob.id).filter(SyncJob.active_account_id == ConnectedAccount.id).exists()
        due = db.query(ConnectedAccount.id, ConnectedAccount.user_id).filter(
            ConnectedAccount.encrypted_credentials.is_not(None), ConnectedAccount.requires_reauth.is_(False),
            ConnectedAccount.sync_paused.is_(False), ~active,
            or_(ConnectedAccount.next_sync_at.is_(None), ConnectedAccount.next_sync_at <= utcnow()),
        ).order_by(ConnectedAccount.next_sync_at, ConnectedAccount.id).limit(100).all()
        db.rollback()
        for account_id, user_id in due:
            try:
                enqueue_sync(db, user_id, account_id, scheduled=True)
            except HTTPException:
                db.rollback()
        due_jobs = [row[0] for row in db.query(SyncJob.id).filter(
            SyncJob.status == "queued", SyncJob.available_at <= utcnow(),
            or_(SyncJob.dispatch_after.is_(None), SyncJob.dispatch_after <= utcnow()),
        ).order_by(SyncJob.available_at, SyncJob.id).limit(100)]
        db.rollback()
        for job_id in due_jobs:
            if not dispatch_job(db, job_id, publisher):
                break  # One bounded broker failure per maintenance pass.
