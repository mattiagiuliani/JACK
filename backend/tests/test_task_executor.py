from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.tasks.db_models import TaskDB  # noqa: F401
from app.tasks.executor import (
    TaskExecutionConflictError,
    TaskExecutionError,
    TaskExecutor,
)
from app.tasks.manager import TaskManager
from app.tasks.models import TaskStatus
from app.tasks.registry import OperationNotFoundError, OperationRegistry
from app.tasks.repository import TaskRepository
from app.tasks.state_machine import InvalidTaskTransitionError


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

    with pytest.raises(
        TaskExecutionError,
        match="Task execution failed",
    ) as exc_info:
        executor.execute(task.id, failing_operation)

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "Research failed"

    failed_task = manager.get_task(task.id)

    assert failed_task.status == TaskStatus.FAILED
    assert failed_task.result == "Research failed"


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


def test_executor_persists_failure_reason(
    manager: TaskManager,
) -> None:
    task = manager.create_task(
        "Market research",
        "Analyze competitors",
    )

    executor = TaskExecutor(manager)

    def failing_operation() -> str:
        raise RuntimeError("Research API unavailable")

    with pytest.raises(
        TaskExecutionError,
        match="Task execution failed",
    ):
        executor.execute(task.id, failing_operation)

    stored = manager.get_task(task.id)

    assert stored.status == TaskStatus.FAILED
    assert stored.result == "Research API unavailable"


def test_executor_failure_persists_in_database(
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
                title="Analyze competitors",
                description="Collect competitor information",
            )

            def failing_operation() -> str:
                raise RuntimeError("Research API unavailable")

            with pytest.raises(
                TaskExecutionError,
                match="Task execution failed",
            ):
                executor.execute(task.id, failing_operation)

        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))
            recovered = manager.get_task(task.id)

            assert recovered.status == TaskStatus.FAILED
            assert recovered.result == "Research API unavailable"

    finally:
        engine.dispose()


def test_executor_preserves_operation_error_on_finalization_conflict(
    manager: TaskManager,
) -> None:
    task = manager.create_task(
        "Concurrent research",
        "Simulate external completion",
    )

    executor = TaskExecutor(manager)

    def conflicting_operation() -> str:
        manager.complete_task(
            task.id,
            "Completed externally",
        )
        raise RuntimeError("Research API unavailable")

    with pytest.raises(
        TaskExecutionConflictError,
        match="Task state changed",
    ) as exc_info:
        executor.execute(task.id, conflicting_operation)

    cause = exc_info.value.__cause__

    assert isinstance(cause, ExceptionGroup)
    assert len(cause.exceptions) == 2
    assert isinstance(cause.exceptions[0], RuntimeError)
    assert str(cause.exceptions[0]) == "Research API unavailable"
    assert isinstance(
        cause.exceptions[1],
        InvalidTaskTransitionError,
    )

    stored = manager.get_task(task.id)

    assert stored.status == TaskStatus.COMPLETED
    assert stored.result == "Completed externally"


def test_executor_failure_conflict_preserves_database_state(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'failure_conflict.db').as_posix()}"
    engine = create_engine(database_url)

    try:
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))
            executor = TaskExecutor(manager)

            task = manager.create_task(
                "Concurrent validation",
                "Simulate competing finalization",
            )

            def conflicting_operation() -> str:
                manager.complete_task(
                    task.id,
                    "Validated externally",
                )
                raise RuntimeError("Validation API unavailable")

            with pytest.raises(TaskExecutionConflictError):
                executor.execute(task.id, conflicting_operation)

        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))
            stored = manager.get_task(task.id)

            assert stored.status == TaskStatus.COMPLETED
            assert stored.result == "Validated externally"

    finally:
        engine.dispose()
