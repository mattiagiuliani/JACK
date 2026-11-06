from fastapi import FastAPI
from pydantic import BaseModel

from app.config import get_settings
from app.tasks.router import router as tasks_router

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    description="Autonomous Business Builder",
    version=settings.app_version,
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
