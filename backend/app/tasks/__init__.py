from app.tasks import celery_app, ingestion_task

__all__ = ["celery_app", "ingestion_task"]
