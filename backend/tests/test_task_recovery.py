from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.tasks.db_models import TaskDB  # noqa: F401
from app.tasks.manager import TaskManager
from app.tasks.models import TaskStatus
from app.tasks.recovery import TaskRecovery
from app.tasks.repository import TaskRepository


def test_recovery_marks_running_tasks_as_failed() -> None:
    manager = TaskManager()

    running = manager.create_task(
        "Market research",
        "Analyze SaaS opportunities",
    )
    pending = manager.create_task(
        "Competitor analysis",
        "Analyze competitors",
    )

    manager.update_status(running.id, TaskStatus.RUNNING)

    recovery = TaskRecovery(manager)
    recovered_ids = recovery.recover_interrupted_tasks()

    assert recovered_ids == [str(running.id)]

    recovered = manager.get_task(running.id)
    assert recovered.status == TaskStatus.FAILED
    assert recovered.result == "Task interrupted before completion"

    unchanged = manager.get_task(pending.id)
    assert unchanged.status == TaskStatus.PENDING


def test_recovery_is_idempotent() -> None:
    manager = TaskManager()

    task = manager.create_task(
        "Market research",
        "Analyze SaaS opportunities",
    )
    manager.update_status(task.id, TaskStatus.RUNNING)

    recovery = TaskRecovery(manager)

    first = recovery.recover_interrupted_tasks()
    second = recovery.recover_interrupted_tasks()

    assert first == [str(task.id)]
    assert second == []


def test_recovery_persists_across_database_sessions(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    engine = create_engine(database_url)

    try:
        Base.metadata.create_all(engine)

        # Prima sessione: simuliamo un task interrotto.
        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))

            task = manager.create_task(
                title="Market research",
                description="Analyze business opportunities",
            )
            manager.update_status(task.id, TaskStatus.RUNNING)

        # Seconda sessione: JACK viene riavviato.
        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))
            recovery = TaskRecovery(manager)

            recovered_ids = recovery.recover_interrupted_tasks()

            assert recovered_ids == [str(task.id)]

        # Terza sessione: verifichiamo la persistenza.
        with Session(engine) as session:
            manager = TaskManager(TaskRepository(session))
            recovered = manager.get_task(task.id)

            assert recovered.status == TaskStatus.FAILED
            assert recovered.result == ("Task interrupted before completion")

    finally:
        engine.dispose()
