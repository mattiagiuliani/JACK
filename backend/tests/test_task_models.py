from uuid import UUID

import pytest
from pydantic import ValidationError

from app.tasks.models import Task, TaskPriority, TaskStatus


def test_task_creation() -> None:
    task = Task(
        title="Market research",
        description="Analyze SaaS opportunities",
    )

    assert isinstance(task.id, UUID)
    assert task.status == TaskStatus.PENDING
    assert task.priority == TaskPriority.MEDIUM
    assert task.result is None


def test_tasks_have_unique_ids() -> None:
    first = Task(title="First", description="First task")
    second = Task(title="Second", description="Second task")

    assert first.id != second.id


def test_empty_title_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Task(title="", description="Invalid task")


def test_invalid_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Task(
            title="Research",
            description="Analyze market",
            status="unknown",  # type: ignore[arg-type]
        )


def test_assignment_is_validated() -> None:
    task = Task(title="Research", description="Analyze market")

    with pytest.raises(ValidationError):
        task.title = ""
