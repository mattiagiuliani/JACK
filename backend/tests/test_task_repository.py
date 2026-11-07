from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.tasks.db_models import TaskDB  # noqa: F401
from app.tasks.models import Task, TaskPriority, TaskStatus
from app.tasks.repository import TaskRepository


@pytest.fixture
def repository(
    tmp_path: Path,
) -> Generator[TaskRepository, None, None]:
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
    assert saved.status == TaskStatus.PENDING


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


def test_get_nonexistent_task(
    repository: TaskRepository,
) -> None:
    assert repository.get(uuid4()) is None


def test_list_tasks(repository: TaskRepository) -> None:
    repository.save(
        Task(
            title="First",
            description="First task",
        )
    )

    repository.save(
        Task(
            title="Second",
            description="Second task",
            priority=TaskPriority.HIGH,
        )
    )

    tasks = repository.list_all()

    assert len(tasks) == 2
    assert {task.title for task in tasks} == {
        "First",
        "Second",
    }


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


def test_claim_pending_task_is_idempotent(
    repository: TaskRepository,
) -> None:
    task = Task(
        title="Market research",
        description="Analyze competitors",
    )

    repository.save(task)

    first_claim = repository.claim_pending_task(task.id)
    second_claim = repository.claim_pending_task(task.id)

    assert first_claim is not None
    assert first_claim.status == TaskStatus.RUNNING
    assert second_claim is None

    stored = repository.get(task.id)

    assert stored is not None
    assert stored.status == TaskStatus.RUNNING


def test_concurrent_claim_allows_only_one_winner(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'concurrent.db').as_posix()}"

    engine = create_engine(
        database_url,
        connect_args={"timeout": 10},
    )

    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            repository = TaskRepository(session)

            task = repository.save(
                Task(
                    title="Concurrent research",
                    description="Test atomic claim",
                )
            )

            task_id = task.id

        barrier = Barrier(2)

        def attempt_claim() -> bool:
            with Session(engine) as session:
                repository = TaskRepository(session)

                barrier.wait(timeout=10)

                claimed = repository.claim_pending_task(task_id)

                return claimed is not None

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt_claim) for _ in range(2)]

            results = [future.result(timeout=15) for future in futures]

        assert results.count(True) == 1
        assert results.count(False) == 1

        with Session(engine) as session:
            repository = TaskRepository(session)
            stored = repository.get(task_id)

            assert stored is not None
            assert stored.status == TaskStatus.RUNNING

    finally:
        engine.dispose()


def test_transition_running_to_completed(
    repository: TaskRepository,
) -> None:
    task = repository.save(
        Task(
            title="Research",
            description="Analyze market",
        )
    )

    repository.claim_pending_task(task.id)

    completed = repository.transition_running_task(
        task.id,
        TaskStatus.COMPLETED,
        "Research completed",
    )

    assert completed is not None
    assert completed.status == TaskStatus.COMPLETED
    assert completed.result == "Research completed"


def test_terminal_transition_cannot_be_overwritten(
    repository: TaskRepository,
) -> None:
    task = repository.save(
        Task(
            title="Research",
            description="Analyze market",
        )
    )

    repository.claim_pending_task(task.id)

    completed = repository.transition_running_task(
        task.id,
        TaskStatus.COMPLETED,
        "Success",
    )

    failed = repository.transition_running_task(
        task.id,
        TaskStatus.FAILED,
        "Late failure",
    )

    assert completed is not None
    assert failed is None

    stored = repository.get(task.id)

    assert stored is not None
    assert stored.status == TaskStatus.COMPLETED
    assert stored.result == "Success"


def test_transition_running_rejects_invalid_target(
    repository: TaskRepository,
) -> None:
    task = repository.save(
        Task(
            title="Research",
            description="Analyze market",
        )
    )

    repository.claim_pending_task(task.id)

    with pytest.raises(ValueError):
        repository.transition_running_task(
            task.id,
            TaskStatus.PENDING,
            "Invalid transition",
        )

    stored = repository.get(task.id)

    assert stored is not None
    assert stored.status == TaskStatus.RUNNING


def test_concurrent_terminal_transitions_allow_only_one_winner(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'concurrent_terminal.db').as_posix()}"

    engine = create_engine(
        database_url,
        connect_args={"timeout": 10},
    )

    Base.metadata.create_all(engine)

    try:
        with Session(engine) as session:
            repository = TaskRepository(session)

            task = repository.save(
                Task(
                    title="Concurrent terminal transition",
                    description="Test atomic finalization",
                )
            )

            task_id = task.id

            claimed = repository.claim_pending_task(task_id)
            assert claimed is not None
            assert claimed.status == TaskStatus.RUNNING

        barrier = Barrier(2)

        def attempt_transition(
            target_status: TaskStatus,
            result: str,
        ) -> tuple[TaskStatus, str] | None:
            with Session(engine) as session:
                repository = TaskRepository(session)

                barrier.wait(timeout=10)

                updated = repository.transition_running_task(
                    task_id,
                    target_status,
                    result,
                )

                if updated is None:
                    return None

                assert updated.result is not None
                return updated.status, updated.result

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    attempt_transition,
                    TaskStatus.COMPLETED,
                    "Success",
                ),
                pool.submit(
                    attempt_transition,
                    TaskStatus.FAILED,
                    "Failure",
                ),
            ]

            results = [future.result(timeout=15) for future in futures]

        winners = [result for result in results if result is not None]

        assert len(winners) == 1
        assert results.count(None) == 1

        with Session(engine) as session:
            repository = TaskRepository(session)
            stored = repository.get(task_id)

            assert stored is not None
            assert stored.status in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
            }

            assert (stored.status, stored.result) == winners[0]

            if stored.status == TaskStatus.COMPLETED:
                assert stored.result == "Success"
            else:
                assert stored.result == "Failure"

    finally:
        engine.dispose()
