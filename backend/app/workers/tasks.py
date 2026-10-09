import app.models.user  # Register the users FK target outside FastAPI startup.
from app.services.sync_jobs import maintenance, process_job
from app.workers.celery_app import celery_app


@celery_app.task(name="mailbox.sync")
def sync_mailbox(job_id: int):
    process_job(job_id)


@celery_app.task(name="mailbox.maintenance", soft_time_limit=50, time_limit=60)
def maintain_mailboxes():
    maintenance()
