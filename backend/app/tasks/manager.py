from uuid import UUID

from app.tasks.models import Task, TaskPriority, TaskStatus
from app.tasks.state_machine import transition_task


class TaskNotFoundError(LookupError):
    """Raised when a task does not exist."""


class TaskManager:
    def __init__(self) -> None:
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

        self._tasks[task.id] = task
        return task.model_copy(deep=True)

    def get_task(self, task_id: UUID) -> Task:
        task = self._tasks.get(task_id)

        if task is None:
            raise TaskNotFoundError(f"Task {task_id} not found")

        return task.model_copy(deep=True)

    def list_tasks(self) -> list[Task]:
        return [task.model_copy(deep=True) for task in self._tasks.values()]

    def update_status(
        self,
        task_id: UUID,
        new_status: TaskStatus,
    ) -> Task:
        task = self._tasks.get(task_id)

        if task is None:
            raise TaskNotFoundError(f"Task {task_id} not found")

        transition_task(task, new_status)
        return task.model_copy(deep=True)
