from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.tasks.db_models import TaskDB  # noqa: F401
from app.tasks.executor import TaskExecutor
from app.tasks.manager import TaskManager
from app.tasks.models import TaskStatus
from app.tasks.registry import OperationNotFoundError, OperationRegistry
from app.tasks.repository import TaskRepository


@pytest.fixture
def manager() -> TaskManager:
    return TaskManager()


def test_executor_completes_task(manager: TaskManager) -> None:
    task = manager.create_task(
        "Market research",
        "Analyze SaaS opportunities",
    )

    executor = TaskExecutor(manager)

    completed = executor.execute(
        task.id,
        lambda: "Research completed",
    )

    assert completed.status == TaskStatus.COMPLETED
    assert completed.result == "Research completed"

    stored = manager.get_task(task.id)

    assert stored.status == TaskStatus.COMPLETED
    assert stored.result == "Research completed"


def test_executor_marks_failed_task(manager: TaskManager) -> None:
    task = manager.create_task(
        "Market research",
        "Analyze SaaS opportunities",
    )

    executor = TaskExecutor(manager)

    def failing_operation() -> str:
        raise RuntimeError("Research failed")

    with pytest.raises(RuntimeError, match="Research failed"):
        executor.execute(task.id, failing_operation)

    stored = manager.get_task(task.id)

    assert stored.status == TaskStatus.FAILED


def test_executor_persists_result_in_database(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    engine = create_engine(database_url)

    try:
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))
            executor = TaskExecutor(manager)

            task = manager.create_task(
                title="Validate SaaS idea",
                description="Analyze market demand",
            )

            completed = executor.execute(
                task.id,
                lambda: "Market validation completed",
            )

            assert completed.status == TaskStatus.COMPLETED

        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))
            recovered = manager.get_task(task.id)

            assert recovered.status == TaskStatus.COMPLETED
            assert recovered.result == "Market validation completed"

    finally:
        engine.dispose()


def test_execute_registered_operation(
    manager: TaskManager,
) -> None:
    registry = OperationRegistry()
    registry.register("research", lambda: "Market analyzed")

    executor = TaskExecutor(manager, registry)
    task = manager.create_task("Research", "Analyze market")

    completed = executor.execute_registered(task.id, "research")

    assert completed.status == TaskStatus.COMPLETED
    assert completed.result == "Market analyzed"


def test_unknown_registered_operation_keeps_task_pending(
    manager: TaskManager,
) -> None:
    registry = OperationRegistry()
    executor = TaskExecutor(manager, registry)
    task = manager.create_task("Research", "Analyze market")

    with pytest.raises(OperationNotFoundError):
        executor.execute_registered(task.id, "unknown")

    assert manager.get_task(task.id).status == TaskStatus.PENDING


def test_execute_registered_without_registry(
    manager: TaskManager,
) -> None:
    executor = TaskExecutor(manager)
    task = manager.create_task("Research", "Analyze market")

    with pytest.raises(RuntimeError, match="not configured"):
        executor.execute_registered(task.id, "research")

    assert manager.get_task(task.id).status == TaskStatus.PENDING
