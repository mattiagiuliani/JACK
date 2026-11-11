"""Offline execution planning contracts; supplied scope is explicitly a proposal."""

from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.agents.base import Agent
from app.agents.research import ResearchModel, Text
from app.agents.validation import ValidationReport, ValidationTest
from app.portfolio.models import Amount, AuditEvent, Venture
from app.tasks.models import Task

Items = Annotated[tuple[Text, ...], Field(min_length=1, max_length=100)]


class PlannedTask(ResearchModel):
    id: Text
    requirement_ids: Items
    deliverable: Text
    acceptance_criteria: Items
    dependencies: tuple[Text, ...] = ()
    priority: Literal["high", "medium", "low"]
    priority_reason: Text
    estimated_hours: Amount
    estimated_cost: Amount
    estimate_basis: Text
    assumptions: Items
    owner_role: Text
    checkpoint: Text
    requires_human_approval: Literal[True] = True


class Requirement(ResearchModel):
    id: Text
    description: Text
    acceptance_criteria: Items
    basis: Literal["proposal"] = "proposal"


class Risk(ResearchModel):
    description: Text
    mitigation: Text
    stop_rule: Text


class Scope(ResearchModel):
    objective: Text
    requirements: Annotated[
        tuple[Requirement, ...], Field(min_length=1, max_length=100)
    ]
    tasks: Annotated[tuple[PlannedTask, ...], Field(min_length=1, max_length=100)]
    risks: Annotated[tuple[Risk, ...], Field(min_length=1, max_length=100)]
    exclusions: Items
    assumptions: Items
    cost_limit: Amount
    contingency: Amount
    # Zero is a declared estimate, never a claim of free delivery.
    cost_basis: Text

    @model_validator(mode="after")
    def graph(self) -> Self:
        requirements = {r.id for r in self.requirements}
        tasks = {t.id: t for t in self.tasks}
        if len(requirements) != len(self.requirements) or len(tasks) != len(self.tasks):
            raise ValueError("Duplicate requirement or task id")
        covered: set[str] = set()
        for task in self.tasks:
            if not set(task.requirement_ids) <= requirements:
                raise ValueError("Unknown requirement")
            covered.update(task.requirement_ids)
            if len(set(task.dependencies)) != len(task.dependencies):
                raise ValueError("Duplicate dependency")
            if not set(task.dependencies) <= tasks.keys():
                raise ValueError("Unknown dependency")
        if covered != requirements:
            raise ValueError("Every requirement needs a deliverable task")
        pending = {t.id: set(t.dependencies) for t in self.tasks}
        while pending:
            ready = {key for key, deps in pending.items() if not deps}
            if not ready:
                raise ValueError("Task dependency cycle")
            pending = {k: v - ready for k, v in pending.items() if k not in ready}
        if self.total_cost > self.cost_limit:
            raise ValueError("Estimates plus contingency exceed declared cost limit")
        return self

    @property
    def total_cost(self) -> Decimal:
        return sum((t.estimated_cost for t in self.tasks), self.contingency)


class PlanningRequest(ResearchModel):
    venture_id: UUID
    expected_version: int = Field(ge=1)
    actor: Text
    reason: Text
    decision_id: UUID | None = None
    scope: Scope


class PlanningContext(ResearchModel):
    request: PlanningRequest
    venture: Venture
    history: tuple[AuditEvent, ...]
    validation: ValidationReport | None
    decision_clear: bool = False


class ExecutionPlan(ResearchModel):
    outcome: Literal["ready_for_review", "hold", "experiment"]
    reasons: Items
    scope: Scope | None
    estimated_total_cost: Amount | None
    task_order: tuple[Text, ...] = ()
    estimated_total_hours: Amount | None = None
    currency: str
    remaining_budget: Amount
    remaining_capital: Amount
    checkpoints: Items = (
        "Human scope, estimates and risk review before implementation.",
        "Human acceptance review for each deliverable and before any release.",
        "Separate explicit authorization before external contact, spend or deployment.",
    )
    evidence_gaps: tuple[Text, ...] = ()
    proposed_experiments: tuple[ValidationTest, ...] = ()
    execution_authorized: Literal[False] = False


def plan(context: PlanningContext) -> ExecutionPlan:
    venture, request, validation = context.venture, context.request, context.validation
    reasons = []
    outcome: Literal["ready_for_review", "hold", "experiment"] = "ready_for_review"
    if venture.id != request.venture_id or venture.version != request.expected_version:
        raise ValueError("Planning context does not match venture request")
    if venture.status not in ("validating", "experimenting", "operating"):
        reasons.append("Venture lifecycle does not permit MVP planning.")
    if not context.decision_clear:
        reasons.append("Fresh acknowledged portfolio decision required.")
    if request.scope.cost_limit > min(
        venture.budget - venture.spent, venture.capital_limit - venture.spent
    ):
        reasons.append("Proposed ceiling exceeds remaining venture limits.")
    if reasons:
        outcome = "hold"
    if (
        validation is None
        or validation.research.mode != "external"
        or not validation.research.evidence
        or validation.recommendation.action != "proceed"
    ):
        reasons.append("Complete corroborated external validation required.")
        if outcome != "hold":
            outcome = "experiment"
    if validation and validation.recommendation.action == "reject":
        outcome = "hold"
    if not reasons:
        reasons.append(
            "Validated input and acknowledged advice permit a proposed MVP plan; "
            "explicit human plan approval remains required."
        )
    ordered: list[str] = []
    pending = {t.id: set(t.dependencies) for t in request.scope.tasks}
    while pending:
        # Stable topological order; input priorities break ties only among ready tasks.
        priorities = {t.id: t.priority for t in request.scope.tasks}
        rank = {"high": 0, "medium": 1, "low": 2}
        ready = sorted(
            (key for key, deps in pending.items() if not deps),
            key=lambda key: (rank[priorities[key]], key),
        )
        ordered.extend(ready)
        pending = {k: v - set(ready) for k, v in pending.items() if k not in ready}
    return ExecutionPlan(
        outcome=outcome,
        reasons=tuple(reasons),
        scope=request.scope if outcome == "ready_for_review" else None,
        estimated_total_cost=(
            request.scope.total_cost if outcome == "ready_for_review" else None
        ),
        evidence_gaps=tuple(
            gap
            for assessment in validation.assessments
            for gap in assessment.missing_data
        )
        if validation
        else ("Linked validation report missing.",),
        proposed_experiments=(
            validation.proposed_tests
            if validation and outcome != "ready_for_review"
            else ()
        ),
        task_order=tuple(ordered) if outcome == "ready_for_review" else (),
        estimated_total_hours=(
            sum((t.estimated_hours for t in request.scope.tasks), Decimal(0))
            if outcome == "ready_for_review"
            else None
        ),
        currency=venture.currency,
        remaining_budget=venture.budget - venture.spent,
        remaining_capital=venture.capital_limit - venture.spent,
    )


class ExecutionPlannerAgent(Agent):
    """Explicit registration only; never creates executable engine tasks."""

    def execute(self, task: Task) -> str:
        if not task.result:
            raise ValueError("Planner requires resolved PlanningContext JSON")
        return plan(PlanningContext.model_validate_json(task.result)).model_dump_json()
