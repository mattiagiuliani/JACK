from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.portfolio.models import AuditEvent, Command, Creation, Venture
from app.portfolio.service import PortfolioConflict, PortfolioService

router = APIRouter(prefix="/ventures", tags=["portfolio"])
DB = Annotated[Session, Depends(get_db)]
Key = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    ),
]


def execute(
    session: Session,
    key: str,
    request: Creation | Command,
    venture_id: UUID | None = None,
) -> Venture:
    try:
        return PortfolioService(session).apply(key, request, venture_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PortfolioConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("", response_model=Venture, status_code=201)
def create(request: Creation, session: DB, key: Key) -> Venture:
    return execute(session, key, request)


@router.get("", response_model=list[Venture])
def list_ventures(session: DB) -> list[Venture]:
    return PortfolioService(session).list_all()


@router.get("/{venture_id}", response_model=Venture)
def get(venture_id: UUID, session: DB) -> Venture:
    try:
        return PortfolioService(session).get(venture_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{venture_id}/commands", response_model=Venture)
def command(venture_id: UUID, request: Command, session: DB, key: Key) -> Venture:
    return execute(session, key, request, venture_id)


@router.get("/{venture_id}/history", response_model=list[AuditEvent])
def history(venture_id: UUID, session: DB) -> list[AuditEvent]:
    try:
        return PortfolioService(session).history(venture_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
