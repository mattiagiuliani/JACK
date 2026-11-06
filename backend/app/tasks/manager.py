from uuid import UUID

from app.tasks.models import Task, TaskPriority, TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.state_machine import transition_task


class TaskNotFoundError(LookupError):
    """Raised when a task does not exist."""


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

    def update_status(
        self,
        task_id: UUID,
        new_status: TaskStatus,
    ) -> Task:
        task = self.get_task(task_id)

        transition_task(task, new_status)

        if self._repository is not None:
            updated = self._repository.update(task)

            if updated is None:
                raise TaskNotFoundError(f"Task {task_id} not found")

            return updated.model_copy(deep=True)

        self._tasks[task_id] = task
        return task.model_copy(deep=True)
