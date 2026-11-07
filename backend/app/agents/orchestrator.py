"""Explicit synchronous delegation through the existing task lifecycle."""

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.agents.registry import AgentRegistry
from app.tasks.executor import TaskExecutor
from app.tasks.manager import TaskManager


class AgentResult(BaseModel):
    """One completed or failed step, in execution order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent: str
    output: str | None = None
    error: str | None = None


class WorkflowResult(BaseModel):
    """Serializable execution report; task status remains owned by the engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID
    steps: tuple[AgentResult, ...]
    succeeded: bool


class AgentWorkflowError(RuntimeError):
    """Carries partial results and the failed step; chained to the agent error."""

    def __init__(self, result: WorkflowResult) -> None:
        self.result = result
        super().__init__(result.model_dump_json())


class AgentOrchestrator:
    """Runs only explicitly selected registered agents, stopping on first error.

    The preceding output is passed in the next snapshot's result field. Agents
    keep their existing execute(Task) -> str contract. No discovery, retries,
    external calls, or spending capabilities are added by this coordinator.
    """

    def __init__(self, manager: TaskManager, registry: AgentRegistry) -> None:
        self._manager = manager
        self._registry = registry
        self._executor = TaskExecutor(manager)

    def delegate(self, task_id: UUID, agent_name: str) -> WorkflowResult:
        return self.execute_workflow(task_id, [agent_name])

    def execute_workflow(
        self, task_id: UUID, agent_names: Sequence[str]
    ) -> WorkflowResult:
        # Resolve the whole plan before claiming or invoking any agent.
        if isinstance(agent_names, str) or not agent_names:
            raise ValueError("Workflow must contain at least one agent name")
        plan = [(name, self._registry.get(name)) for name in agent_names]

        def run() -> str:
            steps: list[AgentResult] = []
            previous: str | None = None
            for name, agent in plan:
                snapshot = self._manager.get_task(task_id)
                snapshot.result = previous
                try:
                    output = agent.execute(snapshot)
                    if not isinstance(output, str):
                        raise TypeError("Agent output must be a string")
                except Exception as error:
                    steps.append(AgentResult(agent=name, error=str(error)))
                    report = WorkflowResult(
                        task_id=task_id, steps=tuple(steps), succeeded=False
                    )
                    raise AgentWorkflowError(report) from error
                steps.append(AgentResult(agent=name, output=output))
                previous = output
            return WorkflowResult(
                task_id=task_id, steps=tuple(steps), succeeded=True
            ).model_dump_json()

        completed = self._executor.execute(task_id, run)
        assert completed.result is not None
        return WorkflowResult.model_validate_json(completed.result)
