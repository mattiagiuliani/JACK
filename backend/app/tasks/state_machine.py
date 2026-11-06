from app.tasks.models import Task, TaskStatus


class InvalidTaskTransitionError(ValueError):
    """Raised when a task status transition is not allowed."""


ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
        }
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
}


def transition_task(task: Task, new_status: TaskStatus) -> None:
    allowed = ALLOWED_TRANSITIONS[task.status]

    if new_status not in allowed:
        raise InvalidTaskTransitionError(
            f"Cannot transition task from {task.status} to {new_status}"
        )

    task.status = new_status
