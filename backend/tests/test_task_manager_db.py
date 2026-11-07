from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.tasks.db_models import TaskDB  # noqa: F401
from app.tasks.manager import TaskManager
from app.tasks.models import TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.state_machine import InvalidTaskTransitionError


def test_task_persists_across_sessions(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    engine = create_engine(database_url)

    try:
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))

            created = manager.create_task(
                title="Build AI SaaS",
                description="Develop the first MVP",
            )

        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))
            recovered = manager.get_task(created.id)

        assert recovered.id == created.id
        assert recovered.title == "Build AI SaaS"

    finally:
        engine.dispose()


def test_status_transition_persists(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    engine = create_engine(database_url)

    try:
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))

            created = manager.create_task(
                title="Analyze market",
                description="Research potential customers",
            )

            updated = manager.update_status(
                created.id,
                TaskStatus.RUNNING,
            )

            assert updated.status == TaskStatus.RUNNING

        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))

            recovered = manager.get_task(created.id)

            assert recovered.status == TaskStatus.RUNNING

            with pytest.raises(InvalidTaskTransitionError):
                manager.update_status(
                    created.id,
                    TaskStatus.PENDING,
                )

            unchanged = manager.get_task(created.id)

            assert unchanged.status == TaskStatus.RUNNING

    finally:
        engine.dispose()


def test_task_result_persists(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    engine = create_engine(database_url)

    try:
        Base.metadata.create_all(engine)

        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))

            task = manager.create_task(
                title="Market research",
                description="Analyze SaaS opportunities",
            )

            manager.update_status(
                task.id,
                TaskStatus.RUNNING,
            )

            completed = manager.complete_task(
                task.id,
                "Three validated business opportunities",
            )

            assert completed.status == TaskStatus.COMPLETED

        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))

            recovered = manager.get_task(task.id)

            assert recovered.status == TaskStatus.COMPLETED
            assert recovered.result == "Three validated business opportunities"

    finally:
        engine.dispose()
