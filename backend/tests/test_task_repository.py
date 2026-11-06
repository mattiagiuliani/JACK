from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.tasks.db_models import TaskDB  # noqa: F401
from app.tasks.models import Task, TaskPriority, TaskStatus
from app.tasks.repository import TaskRepository


@pytest.fixture
def repository(tmp_path: Path) -> Generator[TaskRepository, None, None]:
    database_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    engine = create_engine(database_url)

    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            yield TaskRepository(session)
    finally:
        engine.dispose()


def test_save_task(repository: TaskRepository) -> None:
    task = Task(
        title="Market research",
        description="Analyze SaaS opportunities",
    )

    saved = repository.save(task)

    assert saved.id == task.id
    assert saved.title == "Market research"
    assert saved.status.value == "pending"


def test_get_task(repository: TaskRepository) -> None:
    task = Task(
        title="Research",
        description="Analyze market",
    )

    repository.save(task)
    found = repository.get(task.id)

    assert found is not None
    assert found.id == task.id
    assert found.title == task.title


def test_get_nonexistent_task(repository: TaskRepository) -> None:

    assert repository.get(uuid4()) is None


def test_list_tasks(repository: TaskRepository) -> None:
    repository.save(Task(title="First", description="First task"))
    repository.save(
        Task(
            title="Second",
            description="Second task",
            priority=TaskPriority.HIGH,
        )
    )

    tasks = repository.list_all()

    assert len(tasks) == 2
    assert {task.title for task in tasks} == {"First", "Second"}


def test_update_task(repository: TaskRepository) -> None:
    task = Task(
        title="Research",
        description="Analyze market",
    )

    repository.save(task)

    task.status = TaskStatus.RUNNING
    updated = repository.update(task)

    assert updated is not None
    assert updated.status == TaskStatus.RUNNING

    found = repository.get(task.id)

    assert found is not None
    assert found.status == TaskStatus.RUNNING


def test_update_nonexistent_task(
    repository: TaskRepository,
) -> None:
    task = Task(
        title="Unknown",
        description="Task not stored",
    )

    assert repository.update(task) is None
