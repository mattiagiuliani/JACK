import pytest

from app.agents import (
    Agent,
    AgentAlreadyRegisteredError,
    AgentNotFoundError,
    AgentRegistry,
)
from app.tasks.executor import TaskExecutionError, TaskExecutor
from app.tasks.manager import TaskClaimError, TaskManager
from app.tasks.models import Task, TaskStatus


class ResearchAgent(Agent):
    def execute(self, task: Task) -> str:
        return f"Analyzed: {task.description}"


def test_agent_contract_requires_execute() -> None:
    class IncompleteAgent(Agent):
        pass

    with pytest.raises(TypeError, match="abstract"):
        IncompleteAgent()  # pyright: ignore[reportAbstractUsage]


def test_registry_returns_registered_instance() -> None:
    registry = AgentRegistry()
    agent = ResearchAgent()
    registry.register("research", agent)
    assert registry.get("research") is agent


def test_duplicate_preserves_original_agent() -> None:
    registry = AgentRegistry()
    original = ResearchAgent()
    registry.register("research", original)
    with pytest.raises(AgentAlreadyRegisteredError):
        registry.register("research", ResearchAgent())
    assert registry.get("research") is original


@pytest.mark.parametrize("name", ["", " ", "\t\n"])
def test_blank_names_are_rejected(name: str) -> None:
    registry = AgentRegistry()
    with pytest.raises(ValueError, match="empty"):
        registry.register(name, ResearchAgent())
    assert registry.list_agents() == []


def test_invalid_agent_is_rejected() -> None:
    registry = AgentRegistry()
    with pytest.raises(TypeError, match="contract"):
        registry.register("invalid", object())  # pyright: ignore[reportArgumentType]
    assert registry.list_agents() == []


def test_missing_agent() -> None:
    with pytest.raises(AgentNotFoundError):
        AgentRegistry().get("unknown")


def test_listing_is_sorted_and_independent() -> None:
    registry = AgentRegistry()
    assert registry.list_agents() == []
    registry.register("validation", ResearchAgent())
    registry.register("research", ResearchAgent())
    names = registry.list_agents()
    assert names == ["research", "validation"]
    names.clear()
    assert registry.list_agents() == ["research", "validation"]
    assert AgentRegistry().list_agents() == []


def test_agent_runs_through_existing_executor() -> None:
    manager = TaskManager()
    task = manager.create_task("Research", "SaaS demand")
    registry = AgentRegistry()
    registry.register("research", ResearchAgent())
    agent = registry.get("research")
    executor = TaskExecutor(manager)
    completed = executor.execute(
        task.id, lambda: agent.execute(manager.get_task(task.id))
    )
    assert completed.status == TaskStatus.COMPLETED
    assert manager.get_task(task.id).result == "Analyzed: SaaS demand"
    with pytest.raises(TaskClaimError):
        executor.execute(task.id, lambda: pytest.fail("Agent ran twice"))


def test_agent_failure_uses_existing_task_failure_handling() -> None:
    class FailingAgent(Agent):
        def execute(self, task: Task) -> str:
            assert task.status == TaskStatus.RUNNING
            task.description = "Local snapshot only"
            raise RuntimeError("Research unavailable")

    manager = TaskManager()
    task = manager.create_task("Research", "SaaS demand")
    executor = TaskExecutor(manager)
    agent = FailingAgent()
    with pytest.raises(TaskExecutionError):
        executor.execute(task.id, lambda: agent.execute(manager.get_task(task.id)))
    stored = manager.get_task(task.id)
    assert stored.status == TaskStatus.FAILED
    assert stored.result == "Research unavailable"
    assert stored.description == "SaaS demand"


def test_unknown_agent_does_not_claim_task() -> None:
    manager = TaskManager()
    task = manager.create_task("Research", "SaaS demand")
    with pytest.raises(AgentNotFoundError):
        AgentRegistry().get("unknown")
    assert manager.get_task(task.id).status == TaskStatus.PENDING
