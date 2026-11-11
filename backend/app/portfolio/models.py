"""Typed portfolio snapshots; decimals are serialized losslessly as strings."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.agents.research import ResearchModel, Text
from app.agents.validation import ValidationReport

Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
Amount = Annotated[
    Decimal, Field(ge=0, max_digits=24, decimal_places=6, allow_inf_nan=False)
]
State = Literal[
    "idea",
    "researching",
    "validating",
    "experimenting",
    "operating",
    "paused",
    "closed",
]
TRANSITIONS: dict[str, set[str]] = {
    "idea": {"researching", "closed"},
    "researching": {"validating", "paused", "closed"},
    "validating": {"experimenting", "paused", "closed"},
    "experimenting": {"operating", "validating", "paused", "closed"},
    "operating": {"paused", "closed"},
    "paused": {"researching", "validating", "experimenting", "operating", "closed"},
    "closed": set(),
}


class CreateVenture(ResearchModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    description: Text
    currency: Currency
    capital_limit: Amount
    budget: Amount

    @model_validator(mode="after")
    def check_budget(self) -> Self:
        if self.budget > self.capital_limit:
            raise ValueError("Budget exceeds capital limit")
        return self


class Transition(ResearchModel):
    kind: Literal["transition"]
    status: State


class Limits(ResearchModel):
    kind: Literal["limits"]
    capital_limit: Amount
    budget: Amount


class Expense(ResearchModel):
    kind: Literal["expense"]
    amount: Amount
    currency: Currency
    incurred_at: AwareDatetime
    description: Text
    external_reference: Text


class Metric(ResearchModel):
    kind: Literal["metric"]
    name: Text
    value: Annotated[
        Decimal, Field(max_digits=24, decimal_places=6, allow_inf_nan=False)
    ]
    unit: Text
    currency: Currency | None = None
    basis: Literal["observed", "estimated"]
    period_start: AwareDatetime
    period_end: AwareDatetime
    source: Text
    methodology: Text

    @model_validator(mode="after")
    def check_period(self) -> Self:
        if self.period_end < self.period_start:
            raise ValueError("Invalid metric period")
        if (self.unit == "money") != (self.currency is not None):
            raise ValueError("Money metrics require currency; other units omit it")
        return self


class AssessmentLink(ResearchModel):
    kind: Literal["assessment"]
    task_id: UUID
    report: ValidationReport
    evidence_ids: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def check_evidence(self) -> Self:
        known = {e.id for e in self.report.research.evidence}
        if not set(self.evidence_ids) <= known:
            raise ValueError("Unknown evidence reference")
        return self


Change = Annotated[
    Transition | Limits | Expense | Metric | AssessmentLink, Field(discriminator="kind")
]


class Command(ResearchModel):
    expected_version: int = Field(ge=1)
    actor: Text
    reason: Text
    change: Change


class Creation(ResearchModel):
    actor: Text
    reason: Text
    venture: CreateVenture


class Venture(CreateVenture):
    id: UUID
    status: State = "idea"
    version: int = 1
    paused_from: State | None = None
    spent: Amount = Decimal(0)
    created_at: datetime
    updated_at: datetime


class AuditEvent(ResearchModel):
    sequence: int
    venture_id: UUID
    actor: str
    reason: str
    recorded_at: datetime
    request: Creation | Command
    result: Venture
