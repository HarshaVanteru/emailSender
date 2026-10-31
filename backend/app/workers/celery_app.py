from celery import Celery

from app.core import config

celery_app = Celery("email_sender", broker=config.REDIS_URL, include=["app.workers.tasks"])
celery_app.conf.update(
    task_serializer="json", accept_content=["json"], result_serializer="json",
    task_ignore_result=True, task_acks_late=True, task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True,
    broker_connection_timeout=3, task_publish_retry=False,
    broker_transport_options={"visibility_timeout": config.SYNC_TASK_TIME_LIMIT + 120,
                              "socket_connect_timeout": 3, "socket_timeout": 3},
    task_soft_time_limit=config.SYNC_TASK_TIME_LIMIT - 10,
    task_time_limit=config.SYNC_TASK_TIME_LIMIT,
    timezone="UTC", enable_utc=True,
    task_routes={"mailbox.triage": {"queue": "gmail-ai"},
                 "mailbox.ai": {"queue": "gmail-ai"},
                 "mailbox.send": {"queue": "gmail-send"},
                 "mailbox.historical": {"queue": "gmail-sync"},
                 "mailbox.sync": {"queue": "gmail-sync"},
                 "mailbox.maintenance": {"queue": "gmail-maintenance"},
                 "mailbox.watch_renewal": {"queue": "gmail-maintenance"}},
    beat_schedule={"mailbox-triage": {"task": "mailbox.triage", "schedule": 30.0},
                   "mailbox-maintenance": {"task": "mailbox.maintenance", "schedule": 30.0},
                   "gmail-watch-renewal": {"task": "mailbox.watch_renewal", "schedule": 60.0}},
)


def publish_job(job_id: int):
    # Only identifiers enter Redis. Credentials and message bodies stay server-side.
    celery_app.send_task("mailbox.sync", args=[job_id], queue="gmail-sync", retry=False)
