from celery import Celery
from celery.signals import setup_logging

from egolabs.config import get_settings
from egolabs.logs import configure_logging

settings = get_settings()

celery_app = Celery("egolabs", broker=settings.redis_url, include=["egolabs.worker.tasks"])
celery_app.conf.update(
    task_acks_late=True,  # a job survives a worker crash
    worker_prefetch_multiplier=1,  # long GPU jobs: don't hoard tasks
    task_track_started=True,
    task_ignore_result=True,  # results live in the jobs table, not the broker
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    # The scheduler service (`celery beat`) sends only this: pipeline schedules live in the database.
    beat_schedule={"pipelines-tick": {"task": "egolabs.pipelines.tick", "schedule": 60.0}},
)


@setup_logging.connect
def _configure_logging(**_: object) -> None:
    configure_logging(settings.log_level)
