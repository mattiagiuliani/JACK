from collections.abc import Callable
from uuid import UUID

from app.tasks.manager import TaskManager
from app.tasks.models import Task, TaskStatus
from app.tasks.registry import OperationRegistry


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
        self.manager.update_status(task_id, TaskStatus.RUNNING)

        try:
            result = operation()
        except Exception:
            self.manager.update_status(task_id, TaskStatus.FAILED)
            raise

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
