from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents import (
    Agent,
    AgentNotFoundError,
    AgentOrchestrator,
    AgentRegistry,
    AgentWorkflowError,
    WorkflowResult,
)
from app.db.base import Base
from app.tasks.db_models import TaskDB  # noqa: F401
from app.tasks.executor import TaskExecutionConflictError, TaskExecutionError
from app.tasks.manager import TaskClaimError, TaskManager
from app.tasks.models import Task, TaskStatus
from app.tasks.repository import TaskRepository


class RecordingAgent(Agent):
    def __init__(self, fail: bool = False) -> None:
        self.inputs: list[Task] = []
        self.fail = fail

    def execute(self, task: Task) -> str:
        self.inputs.append(task.model_copy(deep=True))
        task.description = "local mutation"
        if self.fail:
            raise RuntimeError("agent unavailable")
        return f"processed({task.result or self.inputs[-1].description})"


def setup_workflow(manager: TaskManager) -> tuple[AgentOrchestrator, RecordingAgent]:
    registry = AgentRegistry()
    agent = RecordingAgent()
    registry.register("worker", agent)
    return AgentOrchestrator(manager, registry), agent


def test_sequential_handoff_and_snapshot_isolation() -> None:
    manager = TaskManager()
    task = manager.create_task("Workflow", "input")
    orchestrator, agent = setup_workflow(manager)
    report = orchestrator.execute_workflow(task.id, ["worker", "worker"])
    assert report.succeeded
    assert [s.output for s in report.steps] == [
        "processed(input)",
        "processed(processed(input))",
    ]
    assert [t.result for t in agent.inputs] == [None, "processed(input)"]
    assert all(t.status == TaskStatus.RUNNING for t in agent.inputs)
    assert all(t.description == "input" for t in agent.inputs)
    stored = manager.get_task(task.id)
    assert stored.description == "input"
    assert stored.status == TaskStatus.COMPLETED
    assert WorkflowResult.model_validate_json(stored.result or "") == report
    with pytest.raises(TaskClaimError):
        orchestrator.delegate(task.id, "worker")
    assert len(agent.inputs) == 2


def test_single_delegation() -> None:
    manager = TaskManager()
    task = manager.create_task("Single", "input")
    orchestrator, _ = setup_workflow(manager)
    assert len(orchestrator.delegate(task.id, "worker").steps) == 1


@pytest.mark.parametrize("names", [[], "worker"])
def test_invalid_plan_leaves_task_pending(names: list[str] | str) -> None:
    manager = TaskManager()
    task = manager.create_task("Invalid", "input")
    orchestrator, agent = setup_workflow(manager)
    with pytest.raises(ValueError):
        orchestrator.execute_workflow(task.id, names)
    assert manager.get_task(task.id).status == TaskStatus.PENDING
    assert agent.inputs == []


def test_whole_plan_is_resolved_before_execution() -> None:
    manager = TaskManager()
    task = manager.create_task("Unknown", "input")
    orchestrator, agent = setup_workflow(manager)
    with pytest.raises(AgentNotFoundError):
        orchestrator.execute_workflow(task.id, ["worker", "missing"])
    assert agent.inputs == []
    assert manager.get_task(task.id).status == TaskStatus.PENDING


@pytest.mark.parametrize("failure_index", [0, 1])
def test_failure_preserves_partial_results_and_stops(failure_index: int) -> None:
    manager = TaskManager()
    task = manager.create_task("Failure", "input")
    registry = AgentRegistry()
    good, bad, skipped = RecordingAgent(), RecordingAgent(True), RecordingAgent()
    registry.register("good", good)
    registry.register("bad", bad)
    registry.register("skipped", skipped)
    names = ["good"] * failure_index + ["bad", "skipped"]
    with pytest.raises(TaskExecutionError) as caught:
        AgentOrchestrator(manager, registry).execute_workflow(task.id, names)
    cause = caught.value.__cause__
    assert isinstance(cause, AgentWorkflowError)
    assert isinstance(cause.__cause__, RuntimeError)
    assert not cause.result.succeeded
    assert len(cause.result.steps) == failure_index + 1
    assert cause.result.steps[-1].error == "agent unavailable"
    assert skipped.inputs == []
    stored = manager.get_task(task.id)
    assert stored.status == TaskStatus.FAILED
    assert WorkflowResult.model_validate_json(stored.result or "") == cause.result


def test_invalid_agent_output_fails_task() -> None:
    class InvalidAgent(Agent):
        def execute(self, task: Task) -> str:
            return None  # pyright: ignore[reportReturnType]

    manager = TaskManager()
    task = manager.create_task("Invalid output", "input")
    registry = AgentRegistry()
    registry.register("invalid", InvalidAgent())
    with pytest.raises(TaskExecutionError):
        AgentOrchestrator(manager, registry).delegate(task.id, "invalid")
    assert manager.get_task(task.id).status == TaskStatus.FAILED


def test_failure_conflict_retains_engine_semantics() -> None:
    manager = TaskManager()
    task = manager.create_task("Conflict", "input")

    class ConflictingAgent(Agent):
        def execute(self, task: Task) -> str:
            manager.complete_task(task.id, "external completion")
            raise RuntimeError("agent failure")

    registry = AgentRegistry()
    registry.register("conflict", ConflictingAgent())
    with pytest.raises(TaskExecutionConflictError):
        AgentOrchestrator(manager, registry).delegate(task.id, "conflict")
    assert manager.get_task(task.id).result == "external completion"


@pytest.mark.parametrize("fail", [False, True])
def test_reports_survive_database_reload(tmp_path: Path, fail: bool) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'agents.db').as_posix()}")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))
            task = manager.create_task("Persisted workflow", "input")
            registry = AgentRegistry()
            registry.register("worker", RecordingAgent(fail))
            orchestrator = AgentOrchestrator(manager, registry)
            if fail:
                with pytest.raises(TaskExecutionError):
                    orchestrator.delegate(task.id, "worker")
            else:
                orchestrator.execute_workflow(task.id, ["worker", "worker"])
        with Session(engine) as session:
            stored = TaskManager(TaskRepository(session)).get_task(task.id)
            report = WorkflowResult.model_validate_json(stored.result or "")
            assert report.task_id == task.id
            assert report.succeeded == (not fail)
            assert stored.status == (
                TaskStatus.FAILED if fail else TaskStatus.COMPLETED
            )
    finally:
        engine.dispose()


def test_workflow_with_two_distinct_agents() -> None:
    manager = TaskManager()
    task = manager.create_task("Research and validate", "market")
    registry = AgentRegistry()
    research, validation = RecordingAgent(), RecordingAgent()
    registry.register("research", research)
    registry.register("validation", validation)
    report = AgentOrchestrator(manager, registry).execute_workflow(
        task.id, ["research", "validation"]
    )
    assert [step.agent for step in report.steps] == ["research", "validation"]
    assert research.inputs[0].result is None
    assert validation.inputs[0].result == report.steps[0].output
    assert report.steps[1].output == "processed(processed(market))"
    assert report.succeeded
