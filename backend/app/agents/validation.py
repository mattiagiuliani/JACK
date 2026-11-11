"""Conservative offline business validation; recommendations require human review."""

from typing import Literal, Self

from pydantic import model_validator

from app.agents.base import Agent
from app.agents.research import ResearchModel, ResearchReport, Text
from app.tasks.models import Task

Dimension = Literal["demand", "willingness_to_pay", "feasibility", "competition"]
DIMENSIONS: tuple[Dimension, ...] = (
    "demand",
    "willingness_to_pay",
    "feasibility",
    "competition",
)


class EvidenceArgument(ResearchModel):
    evidence_id: Text
    interpretation: Text


class ValidationTest(ResearchModel):
    dimension: Dimension
    procedure: Text
    decision_rule: Text
    requires_human_approval: Literal[True] = True


class Assessment(ResearchModel):
    dimension: Dimension
    status: Literal["unvalidated", "supported", "contradicted", "mixed"]
    supporting: tuple[EvidenceArgument, ...] = ()
    opposing: tuple[EvidenceArgument, ...] = ()
    observations: tuple[EvidenceArgument, ...] = ()
    missing_data: tuple[Text, ...]
    confidence: Literal["insufficient", "limited", "corroborated"]
    confidence_basis: Text

    @model_validator(mode="after")
    def check_basis(self) -> Self:
        if self.status in ("supported", "mixed") and not self.supporting:
            raise ValueError("Supporting evidence required")
        if self.status in ("contradicted", "mixed") and not self.opposing:
            raise ValueError("Opposing evidence required")
        expected = (
            "mixed"
            if self.supporting and self.opposing
            else "supported"
            if self.supporting
            else "contradicted"
            if self.opposing
            else "unvalidated"
        )
        if self.status != expected:
            raise ValueError("Status must reflect supporting and opposing arguments")
        if self.status == "unvalidated" and self.confidence != "insufficient":
            raise ValueError("Unvalidated assessment has insufficient confidence")
        if self.status == "unvalidated" and not self.missing_data:
            raise ValueError("Unvalidated assessment must identify missing data")
        return self


class Recommendation(ResearchModel):
    action: Literal["proceed", "experiment", "hold", "reject"]
    rationale: Text
    requires_human_review: Literal[True] = True


class ValidationReport(ResearchModel):
    research: ResearchReport
    assessments: tuple[Assessment, ...]
    proposed_tests: tuple[ValidationTest, ...]
    recommendation: Recommendation
    limitations: tuple[Text, ...]

    @model_validator(mode="after")
    def check_references(self) -> Self:
        dimensions = [a.dimension for a in self.assessments]
        if len(dimensions) != len(DIMENSIONS) or set(dimensions) != set(DIMENSIONS):
            raise ValueError("Exactly one assessment per dimension required")
        ids = {e.id for e in self.research.evidence}
        for assessment in self.assessments:
            for argument in (
                *assessment.supporting,
                *assessment.opposing,
                *assessment.observations,
            ):
                if argument.evidence_id not in ids:
                    raise ValueError("Unknown research evidence reference")
            if self.research.mode == "controlled_fixture":
                if assessment.confidence != "insufficient":
                    raise ValueError("Fixtures cannot establish business confidence")
        if not self.limitations:
            raise ValueError("Explicit validation limitations required")
        if {t.dimension for t in self.proposed_tests} != set(DIMENSIONS):
            raise ValueError("Test plans must cover every dimension")
        if self.recommendation.action == "proceed" and any(
            a.status != "supported" or a.confidence != "corroborated" or a.missing_data
            for a in self.assessments
        ):
            raise ValueError("Proceed requires complete corroborated support")
        if self.recommendation.action == "reject" and not any(
            a.status == "contradicted" and a.confidence == "corroborated"
            for a in self.assessments
        ):
            raise ValueError("Reject requires corroborated contrary evidence")
        return self


# Explicit plans, not invented experiment results or numeric success thresholds.
PLANS: dict[Dimension, tuple[str, str, str]] = {
    "demand": (
        "Target segment, recruitment method and observed problem frequency.",
        "Interview intended customers about recent behavior and test a prototype.",
        "Agree recruitment, adoption criteria and stop rules before testing.",
    ),
    "willingness_to_pay": (
        "Direct purchase behavior at a defined offer, price and billing period.",
        "With approval, test a clearly described offer with intended buyers; "
        "record actual commitments separately from stated interest.",
        "Predefine acceptable commitments, cancellations and consent; "
        "public competitor prices alone do not validate willingness to pay.",
    ),
    "feasibility": (
        "Prototype results, delivery constraints, dependencies and operating costs.",
        "Run a bounded technical prototype and review operational dependencies.",
        "Agree acceptance criteria and resource limits with the responsible team.",
    ),
    "competition": (
        "Verified alternatives, comparable offers and customer switching barriers.",
        "Compare dated competitor offers and interview users of alternatives.",
        "Verify scope, region and billing terms; absence of observations "
        "does not establish absence of competitors.",
    ),
}


class BusinessValidationAgent(Agent):
    """Consume ResearchReport JSON from task.result without network or mutation.

    Public-page categories are only routing hints, never semantic evidence of
    validation. Arbitrary source text and hypotheses are not instructions.
    This baseline proposes experiments; it cannot establish business viability.
    """

    def execute(self, task: Task) -> str:
        if not task.result:
            raise ValueError("Validation requires preceding ResearchReport JSON")
        research = ResearchReport.model_validate_json(task.result)
        if research.topic != task.description.strip():
            raise ValueError("Research topic does not match task description")
        routes: dict[str, Dimension] = {
            "customer_problem": "demand",
            "demand_signal": "demand",
            "public_price": "willingness_to_pay",
            "competitor": "competition",
        }
        assessments = []
        for dimension in DIMENSIONS:
            observations = tuple(
                EvidenceArgument(
                    evidence_id=e.id,
                    interpretation="Reviewer-assigned category only; source assertion "
                    "requires direct validation and is neither pro nor contra proof.",
                )
                for e in research.evidence
                if research.mode == "external"
                and research.provider == "commercial-public-pages-v1"
                and routes.get(e.id.split(":", 1)[0]) == dimension
            )
            assessments.append(
                Assessment(
                    dimension=dimension,
                    status="unvalidated",
                    observations=observations,
                    missing_data=(PLANS[dimension][0],),
                    confidence="insufficient",
                    confidence_basis="No direct validation results available. "
                    "Counts, labels and fixtures do not raise confidence.",
                )
            )
        report = ValidationReport(
            research=research,
            assessments=tuple(assessments),
            proposed_tests=tuple(
                ValidationTest(
                    dimension=d, procedure=PLANS[d][1], decision_rule=PLANS[d][2]
                )
                for d in DIMENSIONS
            ),
            recommendation=Recommendation(
                action="experiment"
                if research.mode == "external" and research.evidence
                else "hold",
                rationale="Only observations available; propose reviewed "
                "tests before any business decision."
                if research.mode == "external" and research.evidence
                else "No usable real-world observations; obtain "
                "research and define the target segment before validation.",
            ),
            limitations=(
                "Offline deterministic triage, not a viability verdict or probability.",
                "No experiment executed, money spent or economic action authorized.",
                "Source limitations remain attached in the original research report.",
                "Corroborated means direct relevant results independently reviewed; "
                "Limited means provisional direct evidence; neither is produced here.",
            ),
        )
        return report.model_dump_json(exclude_none=True)
