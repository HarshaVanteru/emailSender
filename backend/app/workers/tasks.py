import app.features.google_login.user  # Register the users FK target outside FastAPI startup.
from app.features.mail_sync.jobs import maintenance, process_job
from app.features.mail_sync.push import renew_due_watches
from app.workers.celery_app import celery_app


@celery_app.task(name="mailbox.sync")
def sync_mailbox(job_id: int):
    process_job(job_id)


@celery_app.task(name="mailbox.maintenance", soft_time_limit=50, time_limit=60)
def maintain_mailboxes():
    maintenance()
    from app.core.database import SessionLocal
    from app.features.mail_sync.historical import dispatch_pending
    with SessionLocal() as db:
        dispatch_pending(db, celery_app.send_task)
        from app.workers.operations import dispatch
        dispatch(db, celery_app.send_task)


@celery_app.task(name="mailbox.historical")
def historical_page(session_id: str):
    from app.features.mail_sync.historical import process_page
    process_page(session_id)


@celery_app.task(name="mailbox.send", soft_time_limit=180, time_limit=240)
def send_message(job_id: str):
    from app.workers.operations import process
    process("send", job_id)


@celery_app.task(name="mailbox.ai", soft_time_limit=180, time_limit=240)
def ai_suggestion(job_id: str):
    from app.workers.operations import process
    process("ai", job_id)


@celery_app.task(name="mailbox.watch_renewal", soft_time_limit=900, time_limit=960)
def renew_gmail_watches():
    renew_due_watches()


@celery_app.task(name="mailbox.triage", soft_time_limit=210, time_limit=240)
def triage_mailboxes():
    from app.features.ai_assistant.mybox import classify_pending
    classify_pending()
