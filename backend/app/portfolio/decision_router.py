from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.portfolio.decisions import (
    DecisionRecord,
    DecisionRequest,
    DecisionService,
    Review,
)
from app.portfolio.router import DB, Key
from app.portfolio.service import PortfolioConflict

router = APIRouter(prefix="/portfolio-decisions", tags=["portfolio decisions"])


def execute(operation: Callable[[], DecisionRecord]) -> DecisionRecord:
    try:
        return operation()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PortfolioConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("", response_model=DecisionRecord, status_code=201)
def create(request: DecisionRequest, session: DB, key: Key) -> DecisionRecord:
    return execute(lambda: DecisionService(session).create(key, request))


@router.get("/{decision_id}", response_model=DecisionRecord)
def get(decision_id: UUID, session: DB) -> DecisionRecord:
    return execute(lambda: DecisionService(session).get(decision_id))


@router.post("/{decision_id}/review", response_model=DecisionRecord)
def review(decision_id: UUID, request: Review, session: DB) -> DecisionRecord:
    return execute(lambda: DecisionService(session).review(decision_id, request))
