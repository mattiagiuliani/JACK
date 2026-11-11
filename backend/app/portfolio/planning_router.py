from collections.abc import Callable
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.agents.execution_planner import PlanningRequest
from app.portfolio.planning import PlanningService, PlanRecord, PlanReview
from app.portfolio.router import DB, Key
from app.portfolio.service import PortfolioConflict

router = APIRouter(prefix="/execution-plans", tags=["execution planning"])


def execute(operation: Callable[[], PlanRecord]) -> PlanRecord:
    try:
        return operation()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PortfolioConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("", response_model=PlanRecord, status_code=201)
def create(request: PlanningRequest, session: DB, key: Key) -> PlanRecord:
    return execute(lambda: PlanningService(session).create(key, request))


@router.get("/{plan_id}", response_model=PlanRecord)
def get(plan_id: UUID, session: DB) -> PlanRecord:
    return execute(lambda: PlanningService(session).get(plan_id))


@router.post("/{plan_id}/review", response_model=PlanRecord)
def review(plan_id: UUID, request: PlanReview, session: DB) -> PlanRecord:
    return execute(lambda: PlanningService(session).review(plan_id, request))
