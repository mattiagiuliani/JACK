"""Evidence-based advisory decisions. Never mutates venture state or spends funds."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import String, select, update
from sqlalchemy import Text as SQLText
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.agents.research import ResearchModel, Text
from app.db.base import Base
from app.portfolio.models import (
    Amount,
    AssessmentLink,
    AuditEvent,
    Command,
    Currency,
    Metric,
    Venture,
)
from app.portfolio.service import PortfolioConflict, PortfolioService


class DecisionDB(Base):
    __tablename__ = "portfolio_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    request: Mapped[str] = mapped_column(SQLText, nullable=False)
    report: Mapped[str] = mapped_column(SQLText, nullable=False)
    review: Mapped[str | None] = mapped_column(SQLText, nullable=True)


class Criterion(ResearchModel):
    name: Text
    unit: Text
    currency: Currency | None = None
    period_start: AwareDatetime
    period_end: AwareDatetime
    minimum: Annotated[
        Decimal, Field(max_digits=24, decimal_places=6, allow_inf_nan=False)
    ]
    rationale: Text

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.period_end < self.period_start:
            raise ValueError("Invalid criterion period")
        if (self.unit == "money") != (self.currency is not None):
            raise ValueError("Money criterion requires currency only")
        return self


class Candidate(ResearchModel):
    venture_id: UUID
    expected_version: int = Field(ge=1)
    proposed_cost: Amount


class DecisionRequest(ResearchModel):
    actor: Text
    reason: Text
    candidates: Annotated[tuple[Candidate, ...], Field(min_length=2, max_length=50)]
    criteria: Annotated[tuple[Criterion, ...], Field(min_length=1, max_length=20)]
    available_capital: dict[Currency, Amount]

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({c.venture_id for c in self.candidates}) != len(self.candidates):
            raise ValueError("Duplicate venture")
        if len({c.name for c in self.criteria}) != len(self.criteria):
            raise ValueError("Duplicate criterion name")
        return self


Action = Literal["investigate", "maintain", "suspend", "expand", "abstain"]


class Advice(ResearchModel):
    venture_id: UUID
    action: Action
    reasons: tuple[Text, ...]
    missing_data: tuple[Text, ...]
    observed: tuple[Metric, ...]
    estimated: tuple[Metric, ...]
    requires_human_review: Literal[True] = True


class DecisionReport(ResearchModel):
    id: UUID
    created_at: datetime
    engine_version: Literal["098-v1"] = "098-v1"
    request: DecisionRequest
    snapshots: tuple[Venture, ...]
    histories: tuple[tuple[AuditEvent, ...], ...]
    recommendations: tuple[Advice, ...]
    comparisons: tuple[Text, ...]
    requires_human_review: Literal[True] = True


class Review(ResearchModel):
    actor: Text
    reason: Text
    outcome: Literal["acknowledged", "rejected"]


class ReviewRecord(Review):
    recorded_at: datetime


class DecisionRecord(ResearchModel):
    report: DecisionReport
    review: ReviewRecord | None = None


def comparable(metric: Metric, criterion: Criterion) -> bool:
    return (
        metric.name == criterion.name
        and metric.unit == criterion.unit
        and metric.currency == criterion.currency
        and metric.period_start == criterion.period_start
        and metric.period_end == criterion.period_end
    )


def evaluate(
    request: DecisionRequest,
    snapshots: tuple[Venture, ...],
    histories: tuple[tuple[AuditEvent, ...], ...],
) -> tuple[tuple[Advice, ...], tuple[str, ...]]:
    advice = []
    totals: dict[str, Decimal] = {}
    for venture, candidate in zip(snapshots, request.candidates, strict=True):
        totals[venture.currency] = (
            totals.get(venture.currency, Decimal(0)) + candidate.proposed_cost
        )
    comparisons = tuple(
        f"{currency}: total proposed cost {total}; declared available capital "
        f"{request.available_capital.get(currency, 'unknown')}. "
        "No allocation or ranking performed."
        for currency, total in sorted(totals.items())
    )
    for venture, history, candidate in zip(
        snapshots, histories, request.candidates, strict=True
    ):
        changes = [e.request.change for e in history if isinstance(e.request, Command)]
        metrics = [c for c in changes if isinstance(c, Metric)]
        links = [c for c in changes if isinstance(c, AssessmentLink)]
        observed = tuple(m for m in metrics if m.basis == "observed")
        estimated = tuple(m for m in metrics if m.basis == "estimated")
        missing: list[str] = []
        reasons: list[str] = []
        checks = []
        for criterion in request.criteria:
            matches = [m for m in observed if comparable(m, criterion)]
            if len(matches) != 1:
                missing.append(
                    f"{criterion.name}: require exactly one comparable observed KPI; "
                    f"found {len(matches)}. Estimates never substitute observations."
                )
            else:
                metric = matches[0]
                checks.append(metric.value >= criterion.minimum)
                reasons.append(
                    f"{criterion.name}: observed {metric.value} vs declared minimum "
                    f"{criterion.minimum}; source {metric.source}; "
                    f"criterion rationale: {criterion.rationale}."
                )
                if metric.period_end > datetime.now(UTC):
                    missing.append(
                        f"{criterion.name}: observation period has not ended."
                    )
        report = links[-1].report if links else None
        if (
            report is None
            or report.research.mode != "external"
            or not report.research.evidence
        ):
            missing.append("Real-world validation evidence required.")
        available = request.available_capital.get(venture.currency)
        if available is None:
            missing.append(f"Available capital unknown for {venture.currency}.")
        blocked = (
            candidate.proposed_cost > venture.budget - venture.spent
            or candidate.proposed_cost > venture.capital_limit - venture.spent
            or (available is not None and totals[venture.currency] > available)
        )
        if blocked:
            reasons.append(
                "Proposed costs exceed remaining venture limits or simultaneous "
                "portfolio capital; human prioritization/revised plan required."
            )
        reasons.append(
            f"Proposed cost {candidate.proposed_cost} {venture.currency}; "
            f"remaining budget {venture.budget - venture.spent}; remaining capital "
            f"limit {venture.capital_limit - venture.spent}; "
            f"portfolio available capital {available}."
        )
        if report:
            reasons.append(
                f"Validation recommendation: {report.recommendation.action}; "
                f"{report.recommendation.rationale}"
            )
            for assessment in report.assessments:
                missing.extend(assessment.missing_data)
                reasons.append(
                    f"{assessment.dimension}: {assessment.status}, "
                    f"{assessment.confidence}; {assessment.confidence_basis}"
                )
        complete = (
            report is not None
            and report.recommendation.action == "proceed"
            and all(
                a.status == "supported"
                and a.confidence == "corroborated"
                and not a.missing_data
                for a in report.assessments
            )
        )
        action: Action
        if venture.status in ("paused", "closed"):
            action = "abstain"
            reasons.append("Inactive venture; no automatic resume or reopening.")
        elif blocked:
            action = "suspend"
        elif (
            report
            and report.research.mode == "external"
            and report.recommendation.action == "reject"
        ):
            action = "suspend"
        elif missing:
            action = "abstain"
        elif not complete or not all(checks):
            action = "investigate"
        elif venture.status == "operating" and candidate.proposed_cost > 0:
            action = "expand"
        elif venture.status == "operating":
            action = "maintain"
        else:
            action = "investigate"
        reasons.append(
            "Advisory only: human review required; no spending, transition "
            "or capital allocation authorized."
        )
        advice.append(
            Advice(
                venture_id=venture.id,
                action=action,
                reasons=tuple(reasons),
                missing_data=tuple(missing),
                observed=observed,
                estimated=estimated,
            )
        )
    kpi_comparisons = tuple(
        f"{criterion.name} ({criterion.unit}, {criterion.currency}, "
        f"{criterion.period_start.isoformat()} to "
        f"{criterion.period_end.isoformat()}): "
        + "; ".join(
            f"{item.venture_id}: observed "
            f"{[str(m.value) for m in item.observed if comparable(m, criterion)]}; "
            "estimated "
            f"{[str(m.value) for m in item.estimated if comparable(m, criterion)]}"
            for item in advice
        )
        for criterion in request.criteria
    )
    return tuple(advice), comparisons + kpi_comparisons


class DecisionService:
    def __init__(self, session: Session):
        self.session = session

    def get(self, decision_id: UUID) -> DecisionRecord:
        row = self.session.get(DecisionDB, str(decision_id), populate_existing=True)
        if row is None:
            raise LookupError("Decision not found")
        return DecisionRecord(
            report=DecisionReport.model_validate_json(row.report),
            review=ReviewRecord.model_validate_json(row.review) if row.review else None,
        )

    def create(self, key: str, request: DecisionRequest) -> DecisionRecord:
        import re

        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", key):
            raise ValueError("Invalid idempotency key")
        try:
            row = self.session.scalar(select(DecisionDB).where(DecisionDB.key == key))
            if row:
                if row.request != request.model_dump_json():
                    raise PortfolioConflict("Idempotency key reused")
                return self.get(UUID(row.id))
            portfolio = PortfolioService(self.session)
            histories = tuple(
                tuple(portfolio.history(c.venture_id)) for c in request.candidates
            )
            # Derive snapshots from the same append-only histories to avoid torn reads.
            snapshots = tuple(h[-1].result for h in histories)
            if any(
                v.version != c.expected_version
                for v, c in zip(snapshots, request.candidates, strict=True)
            ):
                raise PortfolioConflict("Stale venture version")
            recommendations, comparisons = evaluate(request, snapshots, histories)
            report = DecisionReport(
                id=uuid4(),
                created_at=datetime.now(UTC),
                request=request,
                snapshots=snapshots,
                histories=histories,
                recommendations=recommendations,
                comparisons=comparisons,
            )
            self.session.add(
                DecisionDB(
                    id=str(report.id),
                    key=key,
                    request=request.model_dump_json(),
                    report=report.model_dump_json(),
                )
            )
            self.session.commit()
            return self.get(report.id)
        except (IntegrityError, OperationalError) as exc:
            self.session.rollback()
            raise PortfolioConflict("Concurrent write; retry same key") from exc
        except Exception:
            self.session.rollback()
            raise

    def review(self, decision_id: UUID, request: Review) -> DecisionRecord:
        try:
            record = self.get(decision_id)
            if record.review:
                if (
                    Review.model_validate(
                        record.review.model_dump(exclude={"recorded_at"})
                    )
                    != request
                ):
                    raise PortfolioConflict("Decision already reviewed")
                return record
            portfolio = PortfolioService(self.session)
            if any(
                portfolio.get(v.id).version != v.version
                for v in record.report.snapshots
            ):
                raise PortfolioConflict(
                    "Venture changed; create a fresh decision before review"
                )
            review = ReviewRecord(**request.model_dump(), recorded_at=datetime.now(UTC))
            result = self.session.execute(
                update(DecisionDB)
                .where(DecisionDB.id == str(decision_id), DecisionDB.review.is_(None))
                .values(review=review.model_dump_json())
            )
            assert isinstance(result, CursorResult)
            if result.rowcount != 1:
                raise PortfolioConflict("Concurrent review; reload decision")
            self.session.commit()
            return self.get(decision_id)
        except (IntegrityError, OperationalError) as exc:
            self.session.rollback()
            raise PortfolioConflict("Concurrent review; reload decision") from exc
        except Exception:
            self.session.rollback()
            raise
