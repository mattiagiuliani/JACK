from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from os import getenv

from fastapi import FastAPI
from pydantic import BaseModel

from app.config import get_settings
from app.db.session import SessionLocal
from app.tasks.manager import TaskManager
from app.tasks.recovery import TaskRecovery
from app.tasks.repository import TaskRepository
from app.tasks.router import router as tasks_router


def recover_tasks_on_startup() -> list[str]:
    with SessionLocal() as session:
        manager = TaskManager(TaskRepository(session))
        recovery = TaskRecovery(manager)
        return recovery.recover_interrupted_tasks()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if getenv("JACK_RECOVER_ON_STARTUP") == "1":
        recover_tasks_on_startup()

    yield


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Autonomous Business Builder",
    version=settings.app_version,
    lifespan=lifespan,
)

app.include_router(tasks_router)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="jack-api",
        version=app.version,
    )
