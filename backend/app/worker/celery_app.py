from celery import Celery

from app.config import settings

# The worker of the app: Celery, with Redis between the API and it. Start it with
# `celery -A app.worker.celery_app worker -Q datasets`, and the scheduler with `celery -A app.worker.celery_app beat`.
celery_app = Celery("app", broker=settings.REDIS_URL, include=["app.worker.tasks"])

celery_app.conf.update(
    task_default_queue="datasets",
    # The state is in the database, not in Celery: nobody reads the result of a task.
    task_ignore_result=True,
    # A job is taken off the queue when it is done, not when it starts: a worker that dies gives it back.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # A job can take long: a worker takes one at a time, so the others are not held back behind it.
    worker_prefetch_multiplier=1,
    # Redis gives a job back to the queue if it is not acknowledged after this: longer than the longest job we expect.
    broker_transport_options={"visibility_timeout": 6 * 3600},
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        # The safety net: a version whose job was lost (Redis restarted) or whose worker died is queued again.
        "process-waiting-versions": {"task": "datasets.process_waiting", "schedule": 60.0},
        # Nobody comes back to an upload that was abandoned: its parts would stay in the storage for ever.
        "expire-uploads": {"task": "datasets.expire_uploads", "schedule": 15 * 60.0},
    },
)
