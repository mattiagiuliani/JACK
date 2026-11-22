from collections.abc import Callable
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.development.models import DevelopmentRequest, ExportRequest
from app.development.service import ArtifactRecord, DevelopmentService
from app.portfolio.router import DB, Key
from app.portfolio.service import PortfolioConflict

router = APIRouter(prefix="/development-artifacts", tags=["development"])


def workspace_root() -> Path:
    value = get_settings().development_workspace_root
    if not value:
        raise HTTPException(503, "Local export disabled; configure a workspace root")
    return Path(value)


def execute(operation: Callable[[], ArtifactRecord]) -> ArtifactRecord:
    try:
        return operation()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PortfolioConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            503, "Local workspace unavailable; retry after repair"
        ) from exc


@router.post("", response_model=ArtifactRecord, status_code=201)
def create(request: DevelopmentRequest, session: DB, key: Key) -> ArtifactRecord:
    return execute(lambda: DevelopmentService(session).create(key, request))


@router.get("/{artifact_id}", response_model=ArtifactRecord)
def get(artifact_id: UUID, session: DB) -> ArtifactRecord:
    return execute(lambda: DevelopmentService(session).get(artifact_id))


@router.post("/{artifact_id}/export", response_model=ArtifactRecord)
def export(
    artifact_id: UUID,
    request: ExportRequest,
    session: DB,
    root: Annotated[Path, Depends(workspace_root)],
) -> ArtifactRecord:
    return execute(
        lambda: DevelopmentService(session).export(artifact_id, request, root)
    )
