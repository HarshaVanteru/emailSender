"""Compatibility sends retain their response shape but record durable outcomes."""
import secrets
from datetime import timedelta
from contextlib import contextmanager
from fastapi import HTTPException
from app.core.time import utcnow
from app.workers import operations
from app.workers.operation_models import SendJob


@contextmanager
def receipt(db, user_id, account_id, operation, data):
    row = SendJob(id=secrets.token_hex(32), user_id=user_id, account_id=account_id,
        idempotency_key='legacy-' + secrets.token_hex(24), input_hash=operations.fingerprint(data),
        operation=operation, status='processing', attempts=1,
        payload_ciphertext=None, created_at=utcnow(), available_at=utcnow(),
        lease_token=secrets.token_hex(24), lease_expires_at=utcnow() + timedelta(minutes=5))
    db.add(row)
    db.commit()
    job_id = row.id
    row.rfc_message_id = None if operation == 'legacy_draft' else f'<{job_id}@email-studio.invalid>'
    db.commit()
    from app.integrations.gmail.client import send_correlation
    correlation = send_correlation.set(row.rfc_message_id)
    result = {}
    try:
        yield result
        row = db.query(SendJob).filter_by(id=job_id).first()
        row.status, row.result, row.payload_ciphertext = 'sent', result, None
        row.completed_at, row.lease_token, row.lease_expires_at = utcnow(), None, None
        db.commit()
    except Exception as exc:
        db.rollback()
        row = db.query(SendJob).filter_by(id=job_id).first()
        row.status = 'failed' if isinstance(exc, HTTPException) and exc.status_code < 500 else 'unknown'
        row.error_code = 'unconfirmed_legacy_send'
        row.lease_token = row.lease_expires_at = None
        db.commit()
        raise
    finally:
        send_correlation.reset(correlation)


def tracked_send(db, user_id, account_id, data, callback):
    with receipt(db, user_id, account_id, 'legacy_compose', data) as record:
        result = callback()
        record.update(message_id=result['id'], status='success')
        return result
