from uuid import uuid4

import pytest

from app.tasks.manager import TaskClaimError, TaskManager, TaskNotFoundError
from app.tasks.models import TaskPriority, TaskStatus
from app.tasks.state_machine import InvalidTaskTransitionError


@pytest.fixture
def manager() -> TaskManager:
    return TaskManager()


def test_create_task(manager: TaskManager) -> None:
    task = manager.create_task(
        title="Market research",
        description="Analyze SaaS opportunities",
        priority=TaskPriority.HIGH,
    )

    assert task.title == "Market research"
    assert task.priority == TaskPriority.HIGH
    assert task.status == TaskStatus.PENDING


def test_get_task(manager: TaskManager) -> None:
    created = manager.create_task(
        title="Research",
        description="Analyze market",
    )

    retrieved = manager.get_task(created.id)

    assert retrieved.id == created.id


def test_get_nonexistent_task(manager: TaskManager) -> None:
    with pytest.raises(TaskNotFoundError):
        manager.get_task(uuid4())


def test_list_tasks(manager: TaskManager) -> None:
    manager.create_task("First", "First description")
    manager.create_task("Second", "Second description")

    tasks = manager.list_tasks()

    assert len(tasks) == 2


def test_update_status(manager: TaskManager) -> None:
    task = manager.create_task("Research", "Analyze market")

    updated = manager.update_status(
        task.id,
        TaskStatus.RUNNING,
    )

    assert updated.status == TaskStatus.RUNNING
    assert manager.get_task(task.id).status == TaskStatus.RUNNING


def test_invalid_transition(manager: TaskManager) -> None:
    task = manager.create_task("Research", "Analyze market")

    with pytest.raises(InvalidTaskTransitionError):
        manager.update_status(task.id, TaskStatus.COMPLETED)

    assert manager.get_task(task.id).status == TaskStatus.PENDING


def test_external_mutation_does_not_change_storage(
    manager: TaskManager,
) -> None:
    task = manager.create_task("Research", "Analyze market")
    task.title = "Modified externally"
    task.status = TaskStatus.COMPLETED

    stored = manager.get_task(task.id)

    assert stored.title == "Research"
    assert stored.status == TaskStatus.PENDING


def test_list_returns_independent_copies(
    manager: TaskManager,
) -> None:
    created = manager.create_task("Research", "Analyze market")

    tasks = manager.list_tasks()
    tasks[0].title = "Changed"

    assert manager.get_task(created.id).title == "Research"


def test_complete_task(manager: TaskManager) -> None:
    task = manager.create_task(
        "Market research",
        "Analyze SaaS opportunities",
    )

    manager.update_status(task.id, TaskStatus.RUNNING)

    completed = manager.complete_task(
        task.id,
        "Identified three potential markets",
    )

    assert completed.status == TaskStatus.COMPLETED
    assert completed.result == "Identified three potential markets"

    stored = manager.get_task(task.id)

    assert stored.status == TaskStatus.COMPLETED
    assert stored.result == "Identified three potential markets"


def test_cannot_complete_pending_task(
    manager: TaskManager,
) -> None:
    task = manager.create_task(
        "Market research",
        "Analyze SaaS opportunities",
    )

    with pytest.raises(InvalidTaskTransitionError):
        manager.complete_task(task.id, "Unexpected result")

    stored = manager.get_task(task.id)

    assert stored.status == TaskStatus.PENDING
    assert stored.result is None


def test_fail_task(manager: TaskManager) -> None:
    task = manager.create_task(
        "Research",
        "Analyze market",
    )

    manager.update_status(task.id, TaskStatus.RUNNING)

    failed = manager.fail_task(
        task.id,
        "Connection timeout",
    )

    assert failed.status == TaskStatus.FAILED
    assert failed.result == "Connection timeout"

    stored = manager.get_task(task.id)

    assert stored.status == TaskStatus.FAILED
    assert stored.result == "Connection timeout"


def test_cannot_fail_pending_task(
    manager: TaskManager,
) -> None:
    task = manager.create_task(
        "Research",
        "Analyze market",
    )

    with pytest.raises(InvalidTaskTransitionError):
        manager.fail_task(task.id, "Unexpected error")

    stored = manager.get_task(task.id)

    assert stored.status == TaskStatus.PENDING
    assert stored.result is None


def test_claim_pending_task(manager: TaskManager) -> None:
    task = manager.create_task(
        "Research",
        "Analyze market",
    )

    claimed = manager.claim_task(task.id)

    assert claimed.status == TaskStatus.RUNNING
    assert manager.get_task(task.id).status == TaskStatus.RUNNING


def test_claim_task_twice_raises_error(
    manager: TaskManager,
) -> None:
    task = manager.create_task(
        "Research",
        "Analyze market",
    )

    manager.claim_task(task.id)

    with pytest.raises(TaskClaimError):
        manager.claim_task(task.id)


def test_claim_nonexistent_task(
    manager: TaskManager,
) -> None:
    with pytest.raises(TaskNotFoundError):
        manager.claim_task(uuid4())
