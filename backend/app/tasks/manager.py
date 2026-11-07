from uuid import UUID

from app.tasks.models import Task, TaskPriority, TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.state_machine import transition_task


class TaskNotFoundError(LookupError):
    """Raised when a task does not exist."""


class TaskClaimError(RuntimeError):
    """Raised when a task cannot be claimed for execution."""


class TaskTransitionConflictError(RuntimeError):
    """Raised when an atomic state transition loses a race."""


class TaskManager:
    def __init__(
        self,
        repository: TaskRepository | None = None,
    ) -> None:
        self._repository = repository
        self._tasks: dict[UUID, Task] = {}

    def create_task(
        self,
        title: str,
        description: str,
        priority: TaskPriority = TaskPriority.MEDIUM,
    ) -> Task:
        task = Task(
            title=title,
            description=description,
            priority=priority,
        )

        if self._repository is not None:
            return self._repository.save(task)

        self._tasks[task.id] = task
        return task.model_copy(deep=True)

    def get_task(self, task_id: UUID) -> Task:
        if self._repository is not None:
            task = self._repository.get(task_id)
        else:
            task = self._tasks.get(task_id)

        if task is None:
            raise TaskNotFoundError(f"Task {task_id} not found")

        return task.model_copy(deep=True)

    def list_tasks(self) -> list[Task]:
        if self._repository is not None:
            tasks = self._repository.list_all()
        else:
            tasks = list(self._tasks.values())

        return [task.model_copy(deep=True) for task in tasks]

    def claim_task(self, task_id: UUID) -> Task:
        if self._repository is not None:
            claimed = self._repository.claim_pending_task(task_id)

            if claimed is not None:
                return claimed.model_copy(deep=True)

            existing = self._repository.get(task_id)

            if existing is None:
                raise TaskNotFoundError(f"Task {task_id} not found")

            raise TaskClaimError(
                f"Task {task_id} cannot be claimed from status {existing.status.value}"
            )

        task = self.get_task(task_id)

        if task.status != TaskStatus.PENDING:
            raise TaskClaimError(
                f"Task {task_id} cannot be claimed from status {task.status.value}"
            )

        transition_task(task, TaskStatus.RUNNING)

        self._tasks[task_id] = task
        return task.model_copy(deep=True)

    def update_status(
        self,
        task_id: UUID,
        new_status: TaskStatus,
    ) -> Task:
        task = self.get_task(task_id)

        # Validate the requested transition.
        transition_task(task, new_status)

        if self._repository is not None:
            if new_status == TaskStatus.RUNNING:
                updated = self._repository.claim_pending_task(task_id)
            else:
                updated = self._repository.transition_running_task(
                    task_id,
                    new_status,
                    task.result or "",
                )

            if updated is not None:
                return updated.model_copy(deep=True)

            current = self._repository.get(task_id)

            if current is None:
                raise TaskNotFoundError(f"Task {task_id} not found")

            raise TaskTransitionConflictError(
                f"Task {task_id} changed state during transition"
            )

        self._tasks[task_id] = task
        return task.model_copy(deep=True)

    def _transition_running_task(
        self,
        task_id: UUID,
        new_status: TaskStatus,
        result: str,
    ) -> Task:
        task = self.get_task(task_id)

        # Preserve the existing state-machine validation.
        transition_task(task, new_status)

        if self._repository is not None:
            updated = self._repository.transition_running_task(
                task_id,
                new_status,
                result,
            )

            if updated is not None:
                return updated.model_copy(deep=True)

            # The conditional UPDATE did not modify any row.
            # Distinguish deletion from a concurrent state change.
            current = self._repository.get(task_id)

            if current is None:
                raise TaskNotFoundError(f"Task {task_id} not found")

            raise TaskTransitionConflictError(
                f"Task {task_id} changed state during transition"
            )

        task.result = result
        self._tasks[task_id] = task
        return task.model_copy(deep=True)

    def complete_task(
        self,
        task_id: UUID,
        result: str,
    ) -> Task:
        return self._transition_running_task(
            task_id,
            TaskStatus.COMPLETED,
            result,
        )

    def fail_task(
        self,
        task_id: UUID,
        error: str,
    ) -> Task:
        return self._transition_running_task(
            task_id,
            TaskStatus.FAILED,
            error,
        )
