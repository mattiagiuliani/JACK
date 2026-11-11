"""Atomic aggregate updates and append-only audit/idempotency receipts.

Use a dedicated session per request. No agent invocation or payment operations.
"""

import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.agents.orchestrator import WorkflowResult
from app.agents.validation import ValidationReport
from app.portfolio.db_models import PortfolioEventDB, VentureDB
from app.portfolio.models import (
    TRANSITIONS,
    AssessmentLink,
    AuditEvent,
    Command,
    Creation,
    Expense,
    Limits,
    Transition,
    Venture,
)
from app.tasks.db_models import TaskDB


class PortfolioConflict(ValueError):
    pass


class PortfolioService:
    def __init__(self, session: Session):
        self.session = session

    def get(self, venture_id: UUID) -> Venture:
        row = self.session.get(VentureDB, str(venture_id), populate_existing=True)
        if row is None:
            raise LookupError("Venture not found")
        return Venture.model_validate_json(row.snapshot)

    def list_all(self) -> list[Venture]:
        return [
            Venture.model_validate_json(r.snapshot)
            for r in self.session.scalars(select(VentureDB).order_by(VentureDB.id))
        ]

    def history(self, venture_id: UUID) -> list[AuditEvent]:
        self.get(venture_id)
        return [
            AuditEvent.model_validate_json(r.event)
            for r in self.session.scalars(
                select(PortfolioEventDB)
                .where(PortfolioEventDB.venture_id == str(venture_id))
                .order_by(PortfolioEventDB.version)
            )
        ]

    def apply(
        self, key: str, request: Creation | Command, venture_id: UUID | None = None
    ) -> Venture:
        # Keys are globally scoped, including across create/update endpoints.
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", key):
            raise ValueError("Invalid idempotency key")
        fingerprint = str(venture_id) + ":" + request.model_dump_json()
        try:
            receipt = self.session.get(PortfolioEventDB, key)
            if receipt:
                if receipt.request != fingerprint:
                    raise PortfolioConflict(
                        "Idempotency key reused for another request"
                    )
                return AuditEvent.model_validate_json(receipt.event).result
            now = datetime.now(UTC)
            if isinstance(request, Creation):
                if venture_id is not None:
                    raise ValueError("Creation does not accept an existing venture")
                result = Venture(
                    **request.venture.model_dump(),
                    id=uuid4(),
                    created_at=now,
                    updated_at=now,
                )
                self.session.add(
                    VentureDB(
                        id=str(result.id), version=1, snapshot=result.model_dump_json()
                    )
                )
                self.session.flush()
            else:
                if venture_id is None:
                    raise ValueError("Venture required")
                current = self.get(venture_id)
                if current.version != request.expected_version:
                    raise PortfolioConflict("Stale venture version")
                change = request.change
                values = current.model_dump()
                if isinstance(change, Transition):
                    if change.status not in TRANSITIONS[current.status]:
                        raise PortfolioConflict("Invalid lifecycle transition")
                    if (
                        current.status == "paused"
                        and change.status != "closed"
                        and change.status != current.paused_from
                    ):
                        raise PortfolioConflict(
                            "Paused venture must resume its prior state"
                        )
                    values["paused_from"] = (
                        current.status if change.status == "paused" else None
                    )
                    values["status"] = change.status
                elif isinstance(change, Limits):
                    if (
                        change.budget < current.spent
                        or change.capital_limit < current.spent
                    ):
                        raise PortfolioConflict("Limits below recorded spending")
                    values.update(
                        budget=change.budget, capital_limit=change.capital_limit
                    )
                elif isinstance(change, Expense):
                    if change.currency != current.currency:
                        raise ValueError(
                            "Expense currency differs from venture currency"
                        )
                    # Reference uniqueness prevents duplicates under different keys.
                    if any(
                        isinstance(e.request, Command)
                        and isinstance(e.request.change, Expense)
                        and e.request.change.external_reference
                        == change.external_reference
                        for e in self.history(venture_id)
                    ):
                        raise PortfolioConflict("Expense reference already recorded")
                    spent = current.spent + change.amount
                    if spent > current.budget or spent > current.capital_limit:
                        raise PortfolioConflict(
                            "Recorded expense exceeds budget/capital limit"
                        )
                    values["spent"] = spent
                elif isinstance(change, AssessmentLink):
                    task = self.session.get(TaskDB, str(change.task_id))
                    if task is None or task.status != "completed" or not task.result:
                        raise ValueError("Assessment requires a completed source task")
                    workflow = WorkflowResult.model_validate_json(task.result)
                    if not workflow.succeeded or workflow.task_id != change.task_id:
                        raise ValueError("Invalid source workflow")
                    reports = [
                        s.output for s in workflow.steps if s.output and not s.error
                    ]
                    if not any(
                        self._matches(output, change.report) for output in reports
                    ):
                        raise ValueError("Assessment differs from source task output")
                    if change.report.research.topic != current.description:
                        raise ValueError(
                            "Assessment topic differs from venture description"
                        )
                values.update(version=current.version + 1, updated_at=now)
                result = Venture.model_validate(values)
                outcome = self.session.execute(
                    update(VentureDB)
                    .where(
                        VentureDB.id == str(venture_id),
                        VentureDB.version == request.expected_version,
                    )
                    .values(version=result.version, snapshot=result.model_dump_json())
                )
                assert isinstance(outcome, CursorResult)
                if outcome.rowcount != 1:
                    raise PortfolioConflict("Concurrent venture update")
            event = AuditEvent(
                sequence=result.version,
                venture_id=result.id,
                actor=request.actor,
                reason=request.reason,
                recorded_at=now,
                request=request,
                result=result,
            )
            self.session.add(
                PortfolioEventDB(
                    id=key,
                    venture_id=str(result.id),
                    version=result.version,
                    request=fingerprint,
                    event=event.model_dump_json(),
                )
            )
            self.session.commit()
            return result
        except (IntegrityError, OperationalError) as exc:
            self.session.rollback()
            raise PortfolioConflict(
                "Concurrent write; retry with the same key"
            ) from exc
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _matches(output: str, report: ValidationReport) -> bool:
        try:
            return ValidationReport.model_validate_json(output) == report
        except ValueError:
            return False
