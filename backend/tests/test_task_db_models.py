from sqlalchemy import inspect

from app.db.base import Base
from app.tasks.db_models import TaskDB


def test_task_table_name() -> None:
    assert TaskDB.__tablename__ == "tasks"


def test_task_columns() -> None:
    mapper = inspect(TaskDB)

    columns = {column.key for column in mapper.columns}

    assert columns == {
        "id",
        "title",
        "description",
        "status",
        "priority",
        "result",
    }


def test_task_table_registered() -> None:
    assert "tasks" in Base.metadata.tables
