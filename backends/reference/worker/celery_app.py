from celery import Celery
from celery.signals import worker_process_init

from app.config import settings

celery_app = Celery("call_center", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_soft_time_limit=settings.celery_task_soft_time_limit_sec,
    task_time_limit=settings.celery_task_time_limit_sec,
)

celery_app.autodiscover_tasks(["worker.tasks"])


@worker_process_init.connect
def _prewarm_embed_model(**_: object) -> None:
    from app.services.embed_service import prewarm_embedder

    prewarm_embedder()
