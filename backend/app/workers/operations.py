"""DB-backed outboxes and crash-safe claims shared by independent work queues."""
import hashlib
import json
import secrets
import time
from app.core.observability import log_operation
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.database import SessionLocal
from app.core.time import utcnow
from app.core.token_crypto import encrypt, decrypt
from app.features.mail_sync.service import owned_account
from app.features.mail_sync.events import publish_update
from app.features.mailbox.models import AuditLog
from app.workers.operation_models import SendJob, AiJob

MODELS = {"send": SendJob, "ai": AiJob}


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def payload(job):
    return {"id": job.id, "account_id": job.account_id, "status": job.status,
            "operation": job.operation, "error_code": job.error_code, "result": job.result,
            "attempts": job.attempts}


def get_job(db, kind, user_id, account_id, job_id):
    if account_id is not None:
        owned_account(db, user_id, account_id)
    row = db.query(MODELS[kind]).filter_by(id=job_id, user_id=user_id, account_id=account_id).first()
    if not row:
        raise HTTPException(404, "Job not found.")
    return row


def submit(db, kind, user_id, account_id, operation, data, key, **extra):
    if account_id is not None:
        owned_account(db, user_id, account_id, lock=True)
    model = MODELS[kind]
    digest = fingerprint({"operation": operation, "data": data})
    existing = db.query(model).filter_by(user_id=user_id, account_id=account_id, idempotency_key=key).first()
    if existing:
        if existing.user_id != user_id or existing.input_hash != digest:
            raise HTTPException(409, "Idempotency key was already used for different content.")
        if kind == 'ai' and existing.status == 'failed':
            existing.status, existing.attempts, existing.error_code = 'pending', 0, None
            existing.available_at = utcnow()
            db.commit()
        return existing
    row = model(id=secrets.token_hex(32), user_id=user_id, account_id=account_id,
                idempotency_key=key, input_hash=digest, operation=operation, status="pending",
                payload_ciphertext=encrypt(json.dumps(data)), attempts=0, created_at=utcnow(),
                available_at=utcnow(), **extra)
    db.add(row)
    try:
        db.commit()  # Record intent before any publish or external side effect.
    except IntegrityError:
        db.rollback()
        existing = db.query(model).filter_by(user_id=user_id, account_id=account_id, idempotency_key=key).one()
        if existing.user_id != user_id or existing.input_hash != digest:
            raise HTTPException(409, "Idempotency key conflict.") from None
        return existing
    return row


def claim(db, kind, job_id):
    model = MODELS[kind]
    row = db.query(model).filter_by(id=job_id).with_for_update(skip_locked=True).first()
    if not row or row.status != "pending" or row.available_at > utcnow():
        db.rollback()
        return None
    if row.account_id is not None:
        owned_account(db, row.user_id, row.account_id)
    row.status, row.lease_token = "processing", secrets.token_hex(24)
    row.attempts += 1
    row.lease_expires_at = utcnow() + timedelta(minutes=5)
    token = row.lease_token
    db.commit()
    return token


def process(kind, job_id, session_factory=SessionLocal, executor=None):
    started = time.monotonic()
    with session_factory() as db:
        token = claim(db, kind, job_id)
        if not token:
            return
        model = MODELS[kind]
        row = db.query(model).filter_by(id=job_id).first()
        try:
            if executor is None:
                if kind == "send":
                    from app.features.compose_email.send_jobs import execute_job
                else:
                    from app.features.ai_assistant.jobs import execute_job
                executor = execute_job
            result = executor(db, row, json.loads(decrypt(row.payload_ciphertext)))
            row = db.query(model).filter_by(id=job_id).populate_existing().with_for_update().one()
            if row.status != "processing" or row.lease_token != token:
                db.rollback()
                return
            row.status, row.result, row.error_code = "sent" if kind == "send" else "completed", result, None
            row.completed_at = utcnow()
            row.payload_ciphertext = None  # Do not retain attachment bodies after completion.
            row.lease_expires_at = row.lease_token = None
            db.add(AuditLog(user_id=row.user_id, account_id=row.account_id, action=f"{kind}.{row.operation}",
                            resource_type=f"{kind}_job", resource_id=row.id, outcome="success"))
            db.commit()
            log_operation(kind + '.' + row.operation, row.user_id, row.account_id, row.id, row.status, started)
            if row.account_id is not None:
                publish_update(row.account_id)
        except Exception as exc:
            db.rollback()
            from app.features.mail_sync.jobs import classify_failure
            code, retryable = classify_failure(exc)
            row = db.query(model).filter_by(id=job_id).populate_existing().with_for_update().one()
            if row.status != "processing" or row.lease_token != token:
                db.rollback()
                return
            if kind == "send":
                # Transport, server, and DB failures may follow provider acceptance.
                row.status = "failed" if isinstance(exc, HTTPException) and exc.status_code < 500 else "unknown"
                row.payload_ciphertext = None
            else:
                row.status = "pending" if retryable and row.attempts < 4 else "failed"
                row.available_at = utcnow() + timedelta(seconds=min(300, 15 * 2 ** row.attempts))
            row.error_code = code
            row.lease_expires_at = row.lease_token = None
            db.commit()
            log_operation(kind + '.' + row.operation, row.user_id, row.account_id, row.id, row.status, started, code)
            if row.account_id is not None:
                publish_update(row.account_id)


def dispatch(db, publisher):
    for kind, model in MODELS.items():
        # A crashed send is ambiguous. Never turn it back into a pending send.
        for row in db.query(model).filter(model.status == "processing", model.lease_expires_at <= utcnow()).with_for_update(skip_locked=True):
            row.status = "unknown" if kind == "send" else "pending" if row.attempts < 4 else "failed"
            row.error_code = "worker_lost"
            row.lease_token = row.lease_expires_at = None
            if kind == 'send':
                row.payload_ciphertext = None
        db.commit()
        ids = [row[0] for row in db.query(model.id).filter(model.status == "pending", model.available_at <= utcnow()).limit(100)]
        db.rollback()
        for job_id in ids:
            publisher(f"mailbox.{kind}", args=[job_id], queue=f"gmail-{kind}", retry=False)
