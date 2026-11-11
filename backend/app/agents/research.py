"""Business research boundary with explicit provenance and no market inference."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from app.agents.base import Agent
from app.tasks.models import Task

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ResearchModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(ResearchModel):
    """A claim quoted from an inspectable source, never an inferred signal."""

    id: Text
    statement: Text
    source_uri: Text
    source_title: Text
    excerpt: Text
    kind: Literal["controlled_fixture", "external"]

    source_publication_date: Text | None = None
    source_revision_uri: Text | None = None
    retrieved_at: datetime | None = None
    source_modified_at: datetime | None = None
    retrieval_uri: Text | None = None
    search_uri: Text | None = None

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        prefix = "fixture://" if self.kind == "controlled_fixture" else "https://"
        if not self.source_uri.startswith(prefix) or not self.source_uri[len(prefix) :]:
            raise ValueError("Source URI must identify a fixture or HTTPS source")
        if self.statement not in self.excerpt:
            raise ValueError("Evidence statement must be present in the source excerpt")
        return self


class Hypothesis(ResearchModel):
    statement: Text
    evidence_ids: tuple[Text, ...] = ()
    validation_needed: Text


class ResearchReport(ResearchModel):
    topic: Text
    provider: Text
    mode: Literal["controlled_fixture", "external"]
    evidence: tuple[Evidence, ...] = ()
    hypotheses: tuple[Hypothesis, ...] = ()
    limitations: tuple[Text, ...]

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        ids = [item.id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence IDs must be unique")
        if any(item.kind != self.mode for item in self.evidence):
            raise ValueError("Evidence provenance must match report mode")
        if any(ref not in ids for h in self.hypotheses for ref in h.evidence_ids):
            raise ValueError("Hypothesis references unknown evidence")
        if not self.limitations:
            raise ValueError("Research limitations must be explicit")
        return self


class ResearchProvider(ABC):
    """Offline and Internet adapters implement this boundary explicitly.

    Adapters own retrieval, provenance and failure handling. Registration grants
    no network or spending authorization. Errors propagate to the task engine.
    """

    @abstractmethod
    def research(self, topic: str) -> ResearchReport:
        """Return a validated report for the exact requested topic."""


class ControlledResearchProvider(ResearchProvider):
    """Exact-match lookup in a small, local demonstration corpus."""

    def research(self, topic: str) -> ResearchReport:
        from app.agents.research_corpus import DEMO_TOPIC, DOCUMENT, SOURCE_URI

        evidence = ()
        if topic == DEMO_TOPIC:
            evidence = (
                Evidence(
                    id="demo-1",
                    statement=DOCUMENT,
                    excerpt=DOCUMENT,
                    source_uri=SOURCE_URI,
                    source_title="JACK controlled research demonstration",
                    kind="controlled_fixture",
                ),
            )
        return ResearchReport(
            topic=topic,
            provider="controlled-local-v1",
            mode="controlled_fixture",
            evidence=evidence,
            limitations=(
                "Controlled demonstration data only; no Internet research performed.",
                "No conclusions about demand, competitors, pricing or market size.",
                "Only an exact corpus topic match yields evidence; no match is not "
                "evidence of absent market demand.",
            ),
        )


class BusinessResearchAgent(Agent):
    """Use task.description as the topic; return a JSON ResearchReport."""

    def __init__(self, provider: ResearchProvider | None = None) -> None:
        from app.agents.research_web import configured_research_provider

        self._provider = (
            provider if provider is not None else configured_research_provider()
        )

    def execute(self, task: Task) -> str:
        topic = task.description.strip()
        report = ResearchReport.model_validate(
            self._provider.research(topic).model_dump()
        )
        if report.topic != topic:
            raise ValueError("Provider report topic does not match task description")
        return report.model_dump_json(exclude_none=True)
