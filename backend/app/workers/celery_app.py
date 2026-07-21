"""
Celery application configuration.
"""

from celery import Celery

from app.config import settings

celery_app = Celery(
    "research_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Don't ack task until it's committed (prevents lost tasks on worker crash)
    task_acks_late=True,
    # One heavy LLM task per worker at a time
    worker_prefetch_multiplier=1,
    # Soft limit: send SIGTERM to task (graceful cleanup)
    task_soft_time_limit=600,  # 10 minutes
    # Hard limit: send SIGKILL (absolute max)
    task_time_limit=settings.celery_task_timeout_seconds,
    # Result expiration
    result_expires=86400,  # 24 hours
)
