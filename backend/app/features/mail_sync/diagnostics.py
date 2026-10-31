"""Owner-scoped operational status; no credentials or mail contents."""
from sqlalchemy import func
from app.features.mail_sync.service import owned_account
from app.features.mail_sync.history_models import HistorySession
from app.features.mail_sync.push_models import PushEvent
from app.features.mailbox.models import SyncJob, MessageTriage
from app.workers.operation_models import SendJob, AiJob


def snapshot(db, user_id, account_id):
    account = owned_account(db, user_id, account_id)
    def counts(model, field):
        column = getattr(model, field)
        return dict(db.query(column, func.count()).filter(model.account_id == account_id).group_by(column).all())
    failed = db.query(SyncJob).filter_by(account_id=account_id, status='failed').order_by(SyncJob.id.desc()).limit(10)
    return {'account_id': account_id, 'requires_reauth': account.requires_reauth,
        'sync_paused': account.sync_paused, 'last_synced_at': account.last_synced_at,
        'watch_expiration': account.watch_expiration, 'next_watch_attempt_at': account.next_watch_attempt_at,
        'watch_last_error_code': account.watch_last_error_code,
        'sync_jobs': counts(SyncJob, 'status'), 'historical_sessions': counts(HistorySession, 'status'),
        'push_events': counts(PushEvent, 'status'), 'send_jobs': counts(SendJob, 'status'),
        'ai_jobs': counts(AiJob, 'status'), 'triage': counts(MessageTriage, 'state'),
        'failed_sync_jobs': [{'id': row.id, 'error_code': row.error_code, 'attempts': row.attempts} for row in failed]}
