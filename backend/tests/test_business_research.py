from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents import (
    Agent,
    AgentOrchestrator,
    AgentRegistry,
    BusinessResearchAgent,
    ControlledResearchProvider,
    Evidence,
    Hypothesis,
    ResearchProvider,
    ResearchReport,
    WorkflowResult,
)
from app.agents.research_corpus import DEMO_TOPIC, DOCUMENT, SOURCE_URI
from app.db.base import Base
from app.tasks.executor import TaskExecutionError
from app.tasks.manager import TaskManager
from app.tasks.models import Task, TaskStatus
from app.tasks.repository import TaskRepository


def demo() -> ResearchReport:
    return ControlledResearchProvider().research(DEMO_TOPIC)


def test_deterministic_and_inspectable() -> None:
    task = Task(title="Research", description=DEMO_TOPIC)
    before = task.model_dump()
    agent = BusinessResearchAgent()
    assert agent.execute(task) == agent.execute(task)
    report = ResearchReport.model_validate_json(agent.execute(task))
    assert report == demo()
    assert report.evidence[0].excerpt == DOCUMENT
    assert report.evidence[0].source_uri == SOURCE_URI
    assert report.hypotheses == ()
    assert task.model_dump() == before


def test_unknown_topic_does_not_invent_market_signals() -> None:
    report = ControlledResearchProvider().research("real market opportunity")
    assert report.evidence == report.hypotheses == ()
    assert report.limitations


@pytest.mark.parametrize(
    "change",
    [
        {"id": " "},
        {"source_uri": "https://example.com"},
        {"statement": "invented demand"},
        {"unexpected": True},
    ],
)
def test_invalid_evidence(change: dict[str, object]) -> None:
    data = demo().evidence[0].model_dump() | change
    with pytest.raises(ValidationError):
        Evidence.model_validate(data)


@pytest.mark.parametrize(
    "change",
    [
        {"evidence": [demo().evidence[0], demo().evidence[0]]},
        {
            "hypotheses": [
                Hypothesis(
                    statement="Maybe",
                    evidence_ids=("missing",),
                    validation_needed="Interview customers",
                )
            ]
        },
        {"mode": "external"},
        {"limitations": []},
    ],
)
def test_invalid_report(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ResearchReport.model_validate(demo().model_dump() | change)


def test_hypotheses_remain_separate_and_roundtrip() -> None:
    data = demo().model_dump() | {
        "hypotheses": [
            Hypothesis(
                statement="A workflow may help",
                evidence_ids=("demo-1",),
                validation_needed="Test with users before drawing conclusions",
            )
        ]
    }
    report = ResearchReport.model_validate(data)
    assert ResearchReport.model_validate_json(report.model_dump_json()) == report


@pytest.mark.parametrize("wrong_topic", [False, True])
def test_provider_failure_is_owned_by_engine(wrong_topic: bool) -> None:
    class BadProvider(ResearchProvider):
        def research(self, topic: str) -> ResearchReport:
            if wrong_topic:
                return demo()
            raise RuntimeError("retrieval failed")

    manager = TaskManager()
    task = manager.create_task("Research", "other topic")
    registry = AgentRegistry()
    registry.register("research", BusinessResearchAgent(BadProvider()))
    with pytest.raises(TaskExecutionError):
        AgentOrchestrator(manager, registry).delegate(task.id, "research")
    assert manager.get_task(task.id).status == TaskStatus.FAILED


def test_database_and_sequential_handoff(tmp_path: Path) -> None:
    class Reader(Agent):
        def execute(self, task: Task) -> str:
            report = ResearchReport.model_validate_json(task.result or "")
            assert report.topic == DEMO_TOPIC
            return "reviewed controlled evidence"

    engine = create_engine(f"sqlite:///{(tmp_path / 'research.db').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))
            task = manager.create_task("Research", DEMO_TOPIC)
            registry = AgentRegistry()
            registry.register("business_research", BusinessResearchAgent())
            registry.register("reader", Reader())
            result = AgentOrchestrator(manager, registry).execute_workflow(
                task.id, ["business_research", "reader"]
            )
        with Session(engine) as session:
            stored = TaskManager(TaskRepository(session)).get_task(task.id)
            assert stored.status == TaskStatus.COMPLETED
            assert WorkflowResult.model_validate_json(stored.result or "") == result
            assert (
                ResearchReport.model_validate_json(result.steps[0].output or "")
                == demo()
            )
    finally:
        engine.dispose()
