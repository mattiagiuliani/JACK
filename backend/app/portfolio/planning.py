"""Immutable planning audit and compare-and-set human approval, without execution."""

import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime
from sqlalchemy import String, Text, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.agents.execution_planner import (
    ExecutionPlan,
    PlanningContext,
    PlanningRequest,
    plan,
)
from app.agents.research import ResearchModel
from app.agents.research import Text as NonemptyText
from app.db.base import Base
from app.portfolio.decisions import DecisionRecord, DecisionService
from app.portfolio.models import AssessmentLink, Command
from app.portfolio.service import PortfolioConflict, PortfolioService


class PlanDB(Base):
    __tablename__ = "execution_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    report: Mapped[str] = mapped_column(Text, nullable=False)
    review: Mapped[str | None] = mapped_column(Text, nullable=True)


class PlanReview(ResearchModel):
    actor: NonemptyText
    reason: NonemptyText
    outcome: Literal["approved", "rejected"]


class PlanReviewRecord(PlanReview):
    recorded_at: AwareDatetime


class PlanAudit(ResearchModel):
    id: UUID
    created_at: AwareDatetime
    planner_version: Literal["101-v1"] = "101-v1"
    context: PlanningContext
    decision: DecisionRecord | None
    result: ExecutionPlan


class PlanRecord(ResearchModel):
    audit: PlanAudit
    review: PlanReviewRecord | None = None


class PlanningService:
    def __init__(self, session: Session):
        self.session = session

    def get(self, plan_id: UUID) -> PlanRecord:
        row = self.session.get(PlanDB, str(plan_id), populate_existing=True)
        if row is None:
            raise LookupError("Execution plan not found")
        return PlanRecord(
            audit=PlanAudit.model_validate_json(row.report),
            review=PlanReviewRecord.model_validate_json(row.review)
            if row.review
            else None,
        )

    def create(self, key: str, request: PlanningRequest) -> PlanRecord:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", key):
            raise ValueError("Invalid idempotency key")
        try:
            row = self.session.scalar(select(PlanDB).where(PlanDB.key == key))
            if row:
                if row.request != request.model_dump_json():
                    raise PortfolioConflict("Idempotency key reused")
                return self.get(UUID(row.id))
            history = tuple(PortfolioService(self.session).history(request.venture_id))
            venture = history[-1].result
            if venture.version != request.expected_version:
                raise PortfolioConflict("Stale venture version")
            links = [
                e.request.change
                for e in history
                if isinstance(e.request, Command)
                and isinstance(e.request.change, AssessmentLink)
            ]
            decision = (
                DecisionService(self.session).get(request.decision_id)
                if request.decision_id
                else None
            )
            clear = False
            if (
                decision
                and decision.review
                and decision.review.outcome == "acknowledged"
            ):
                report = decision.report
                matching = [v for v in report.snapshots if v.id == venture.id]
                advice = [
                    a for a in report.recommendations if a.venture_id == venture.id
                ]
                clear = (
                    len(matching) == 1
                    and matching[0].version == venture.version
                    and any(
                        candidate.venture_id == venture.id
                        and candidate.proposed_cost >= request.scope.cost_limit
                        for candidate in report.request.candidates
                    )
                    and len(advice) == 1
                    and not advice[0].missing_data
                    and advice[0].action in ("investigate", "maintain", "expand")
                    and all(
                        PortfolioService(self.session).get(v.id).version == v.version
                        for v in report.snapshots
                    )
                )
            context = PlanningContext(
                request=request,
                venture=venture,
                history=history,
                validation=links[-1].report if links else None,
                decision_clear=clear,
            )
            audit = PlanAudit(
                id=uuid4(),
                created_at=datetime.now(UTC),
                context=context,
                decision=decision,
                result=plan(context),
            )
            self.session.add(
                PlanDB(
                    id=str(audit.id),
                    key=key,
                    request=request.model_dump_json(),
                    report=audit.model_dump_json(),
                )
            )
            self.session.commit()
            return self.get(audit.id)
        except (IntegrityError, OperationalError) as exc:
            self.session.rollback()
            raise PortfolioConflict(
                "Concurrent planning write; retry same key"
            ) from exc
        except Exception:
            self.session.rollback()
            raise

    def review(self, plan_id: UUID, request: PlanReview) -> PlanRecord:
        try:
            record = self.get(plan_id)
            if record.review:
                if (
                    PlanReview.model_validate(
                        record.review.model_dump(exclude={"recorded_at"})
                    )
                    != request
                ):
                    raise PortfolioConflict("Plan already reviewed")
                return record
            if request.outcome == "approved":
                if record.audit.result.outcome != "ready_for_review":
                    raise PortfolioConflict("Hold/experiment plans cannot be approved")
                venture = record.audit.context.venture
                if (
                    PortfolioService(self.session).get(venture.id).version
                    != venture.version
                ):
                    raise PortfolioConflict("Venture changed; create a fresh plan")
            if request.outcome == "approved" and record.audit.decision:
                if any(
                    PortfolioService(self.session).get(v.id).version != v.version
                    for v in record.audit.decision.report.snapshots
                ):
                    raise PortfolioConflict("Portfolio changed; create a fresh plan")
            review = PlanReviewRecord(
                **request.model_dump(), recorded_at=datetime.now(UTC)
            )
            result = self.session.execute(
                update(PlanDB)
                .where(PlanDB.id == str(plan_id), PlanDB.review.is_(None))
                .values(review=review.model_dump_json())
            )
            assert isinstance(result, CursorResult)
            if result.rowcount != 1:
                raise PortfolioConflict("Concurrent review; reload plan")
            self.session.commit()
            return self.get(plan_id)
        except (IntegrityError, OperationalError) as exc:
            self.session.rollback()
            raise PortfolioConflict("Concurrent review; reload plan") from exc
        except Exception:
            self.session.rollback()
            raise
