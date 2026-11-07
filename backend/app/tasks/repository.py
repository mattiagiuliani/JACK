from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.tasks.db_models import TaskDB
from app.tasks.models import Task, TaskPriority, TaskStatus


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _to_task(db_task: TaskDB) -> Task:
        return Task(
            id=UUID(db_task.id),
            title=db_task.title,
            description=db_task.description,
            status=TaskStatus(db_task.status),
            priority=TaskPriority(db_task.priority),
            result=db_task.result,
        )

    def save(self, task: Task) -> Task:
        db_task = TaskDB(
            id=str(task.id),
            title=task.title,
            description=task.description,
            status=task.status.value,
            priority=task.priority.value,
            result=task.result,
        )

        self.session.add(db_task)
        self.session.commit()
        self.session.refresh(db_task)

        return self._to_task(db_task)

    def get(self, task_id: UUID) -> Task | None:
        db_task = self.session.get(TaskDB, str(task_id))

        if db_task is None:
            return None

        return self._to_task(db_task)

    def list_all(self) -> list[Task]:
        statement = select(TaskDB)
        db_tasks = self.session.scalars(statement).all()

        return [self._to_task(task) for task in db_tasks]

    def update(self, task: Task) -> Task | None:
        db_task = self.session.get(TaskDB, str(task.id))

        if db_task is None:
            return None

        db_task.title = task.title
        db_task.description = task.description
        db_task.status = task.status.value
        db_task.priority = task.priority.value
        db_task.result = task.result

        self.session.commit()
        self.session.refresh(db_task)

        return self._to_task(db_task)

    def claim_pending_task(self, task_id: UUID) -> Task | None:
        statement = (
            update(TaskDB)
            .where(
                TaskDB.id == str(task_id),
                TaskDB.status == TaskStatus.PENDING.value,
            )
            .values(status=TaskStatus.RUNNING.value)
        )

        result = self.session.execute(statement)
        assert isinstance(result, CursorResult)

        if result.rowcount != 1:
            self.session.rollback()
            return None

        self.session.commit()
        return self.get(task_id)

    def transition_running_task(
        self,
        task_id: UUID,
        new_status: TaskStatus,
        result: str,
    ) -> Task | None:
        if new_status not in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
        ):
            raise ValueError("Target status must be completed or failed")

        statement = (
            update(TaskDB)
            .where(
                TaskDB.id == str(task_id),
                TaskDB.status == TaskStatus.RUNNING.value,
            )
            .values(
                status=new_status.value,
                result=result,
            )
        )

        execution_result = self.session.execute(statement)
        assert isinstance(execution_result, CursorResult)

        if execution_result.rowcount != 1:
            self.session.rollback()
            return None

        self.session.commit()

        return self.get(task_id)
