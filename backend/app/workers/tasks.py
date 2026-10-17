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


@celery_app.task(name="mailbox.watch_renewal", soft_time_limit=900, time_limit=960)
def renew_gmail_watches():
    renew_due_watches()


@celery_app.task(name="mailbox.triage", soft_time_limit=210, time_limit=240)
def triage_mailboxes():
    from app.features.ai_assistant.mybox import classify_pending
    classify_pending()
