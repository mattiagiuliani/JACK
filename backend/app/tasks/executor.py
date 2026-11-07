from collections.abc import Callable
from uuid import UUID

from app.tasks.manager import (
    TaskManager,
    TaskTransitionConflictError,
)
from app.tasks.models import Task
from app.tasks.registry import OperationRegistry
from app.tasks.state_machine import InvalidTaskTransitionError


class TaskExecutionError(RuntimeError):
    """Raised when a task operation fails."""


class TaskExecutionConflictError(TaskTransitionConflictError):
    """Raised when a failed operation cannot finalize its task."""


class TaskExecutor:
    def __init__(
        self,
        manager: TaskManager,
        registry: OperationRegistry | None = None,
    ) -> None:
        self.manager = manager
        self.registry = registry

    def execute(
        self,
        task_id: UUID,
        operation: Callable[[], str],
    ) -> Task:
        self.manager.claim_task(task_id)

        try:
            result = operation()

        except Exception as operation_error:
            try:
                self.manager.fail_task(
                    task_id,
                    str(operation_error),
                )
            except (
                TaskTransitionConflictError,
                InvalidTaskTransitionError,
            ) as transition_error:
                raise TaskExecutionConflictError(
                    "Task state changed while recording operation failure"
                ) from ExceptionGroup(
                    "Operation failed and task finalization conflicted",
                    [operation_error, transition_error],
                )

            raise TaskExecutionError("Task execution failed") from operation_error

        return self.manager.complete_task(task_id, result)

    def execute_registered(
        self,
        task_id: UUID,
        operation_name: str,
    ) -> Task:
        if self.registry is None:
            raise RuntimeError("Operation registry is not configured")

        operation = self.registry.get(operation_name)
        return self.execute(task_id, operation)
