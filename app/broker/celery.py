from celery import Celery
import os

# Ensure REDIS_URL environment variable is loaded
REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    raise EnvironmentError("REDIS_URL environment variable is not set!")

celery_app = Celery(
    "worker",
    broker=REDIS_URL,
    backend=REDIS_URL
)


celery_app.conf.task_routes = {
    "app.broker.tasks.*": {"queue": "default"},
}

# ⬇️ Import to register tasks
import app.broker.tasks  # Ensure this line is added to register tasks

