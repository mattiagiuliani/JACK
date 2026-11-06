import pytest

from app.tasks.models import Task, TaskStatus
from app.tasks.state_machine import (
    InvalidTaskTransitionError,
    transition_task,
)


def make_task() -> Task:
    return Task(
        title="Market research",
        description="Analyze SaaS opportunities",
    )


def test_pending_to_running() -> None:
    task = make_task()

    transition_task(task, TaskStatus.RUNNING)

    assert task.status == TaskStatus.RUNNING


def test_running_to_completed() -> None:
    task = make_task()

    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.COMPLETED)

    assert task.status == TaskStatus.COMPLETED


def test_running_to_failed() -> None:
    task = make_task()

    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.FAILED)

    assert task.status == TaskStatus.FAILED


def test_pending_to_completed_is_rejected() -> None:
    task = make_task()

    with pytest.raises(InvalidTaskTransitionError):
        transition_task(task, TaskStatus.COMPLETED)

    assert task.status == TaskStatus.PENDING


def test_completed_task_cannot_restart() -> None:
    task = make_task()
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.COMPLETED)

    with pytest.raises(InvalidTaskTransitionError):
        transition_task(task, TaskStatus.RUNNING)


def test_failed_task_cannot_restart() -> None:
    task = make_task()
    transition_task(task, TaskStatus.RUNNING)
    transition_task(task, TaskStatus.FAILED)

    with pytest.raises(InvalidTaskTransitionError):
        transition_task(task, TaskStatus.RUNNING)
