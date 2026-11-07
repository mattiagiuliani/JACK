from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.tasks.db_models import TaskDB  # noqa: F401
from app.tasks.manager import TaskManager, TaskTransitionConflictError
from app.tasks.registry import OperationRegistry
from app.tasks.router import get_operation_registry


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    database_url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"

    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
    )

    Base.metadata.create_all(engine)

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_create_task(client: TestClient) -> None:
    response = client.post(
        "/tasks",
        json={
            "title": "Market research",
            "description": "Analyze Italian SaaS market",
            "priority": "high",
        },
    )

    assert response.status_code == 201

    data = response.json()
    assert data["title"] == "Market research"
    assert data["status"] == "pending"
    assert data["priority"] == "high"
    assert "id" in data


def test_list_tasks(client: TestClient) -> None:
    client.post(
        "/tasks",
        json={
            "title": "Research",
            "description": "Analyze market",
        },
    )

    response = client.get("/tasks")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_task(client: TestClient) -> None:
    created = client.post(
        "/tasks",
        json={
            "title": "Research",
            "description": "Analyze market",
        },
    ).json()

    response = client.get(f"/tasks/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_nonexistent_task(client: TestClient) -> None:
    response = client.get("/tasks/550e8400-e29b-41d4-a716-446655440000")

    assert response.status_code == 404


def test_invalid_task_payload(client: TestClient) -> None:
    response = client.post(
        "/tasks",
        json={
            "title": "",
            "description": "Analyze market",
        },
    )

    assert response.status_code == 422


def test_invalid_task_id(client: TestClient) -> None:
    response = client.get("/tasks/not-a-uuid")

    assert response.status_code == 422


def test_update_task_status(client: TestClient) -> None:
    created = client.post(
        "/tasks",
        json={
            "title": "Market research",
            "description": "Analyze SaaS opportunities",
        },
    ).json()

    response = client.patch(
        f"/tasks/{created['id']}/status",
        json={"status": "running"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "running"

    # Verifica che lo stato sia stato salvato nel database.
    get_response = client.get(f"/tasks/{created['id']}")
    assert get_response.json()["status"] == "running"


def test_invalid_status_transition(client: TestClient) -> None:
    created = client.post(
        "/tasks",
        json={
            "title": "Market research",
            "description": "Analyze SaaS opportunities",
        },
    ).json()

    response = client.patch(
        f"/tasks/{created['id']}/status",
        json={"status": "completed"},
    )

    assert response.status_code == 409


def test_update_nonexistent_task(client: TestClient) -> None:
    response = client.patch(
        "/tasks/550e8400-e29b-41d4-a716-446655440000/status",
        json={"status": "running"},
    )

    assert response.status_code == 404


def test_invalid_status_value(client: TestClient) -> None:
    created = client.post(
        "/tasks",
        json={
            "title": "Market research",
            "description": "Analyze SaaS opportunities",
        },
    ).json()

    response = client.patch(
        f"/tasks/{created['id']}/status",
        json={"status": "unknown"},
    )

    assert response.status_code == 422


def test_execute_task_success(client: TestClient) -> None:
    created = client.post(
        "/tasks",
        json={
            "title": "Market research",
            "description": "Analyze SaaS opportunities",
        },
    )
    assert created.status_code == 201

    task_id = created.json()["id"]

    response = client.post(
        f"/tasks/{task_id}/execute",
        json={"operation": "market_research"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["result"] == ("Market research operation executed")

    stored = client.get(f"/tasks/{task_id}")
    assert stored.status_code == 200
    assert stored.json()["status"] == "completed"
    assert stored.json()["result"] == ("Market research operation executed")


def test_execute_unknown_operation(client: TestClient) -> None:
    created = client.post(
        "/tasks",
        json={
            "title": "Market research",
            "description": "Analyze opportunities",
        },
    )
    task_id = created.json()["id"]

    response = client.post(
        f"/tasks/{task_id}/execute",
        json={"operation": "unknown"},
    )

    assert response.status_code == 400

    stored = client.get(f"/tasks/{task_id}")
    assert stored.json()["status"] == "pending"


def test_execute_missing_task(client: TestClient) -> None:
    from uuid import uuid4

    response = client.post(
        f"/tasks/{uuid4()}/execute",
        json={"operation": "market_research"},
    )

    assert response.status_code == 404


def test_execute_completed_task_conflict(
    client: TestClient,
) -> None:
    created = client.post(
        "/tasks",
        json={
            "title": "Market research",
            "description": "Analyze opportunities",
        },
    )
    task_id = created.json()["id"]

    first = client.post(
        f"/tasks/{task_id}/execute",
        json={"operation": "market_research"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/tasks/{task_id}/execute",
        json={"operation": "market_research"},
    )

    assert second.status_code == 409


def test_execute_task_operation_failure(
    client: TestClient,
) -> None:
    registry = OperationRegistry()

    def failing_operation() -> str:
        raise RuntimeError("Secret internal failure")

    registry.register("failing_operation", failing_operation)

    app.dependency_overrides[get_operation_registry] = lambda: registry

    try:
        created = client.post(
            "/tasks",
            json={
                "title": "Failing research",
                "description": "Test operation failure",
            },
        )

        assert created.status_code == 201
        task_id = created.json()["id"]

        response = client.post(
            f"/tasks/{task_id}/execute",
            json={"operation": "failing_operation"},
        )

        assert response.status_code == 500
        assert response.json() == {"detail": "Task execution failed"}
        assert "Secret internal failure" not in response.text

        stored = client.get(f"/tasks/{task_id}")

        assert stored.status_code == 200
        assert stored.json()["status"] == "failed"
        assert stored.json()["result"] == "Secret internal failure"

    finally:
        app.dependency_overrides.pop(
            get_operation_registry,
            None,
        )


def test_execute_running_task_conflict(
    client: TestClient,
) -> None:
    created = client.post(
        "/tasks",
        json={
            "title": "Market research",
            "description": "Analyze competitors",
        },
    )

    assert created.status_code == 201
    task_id = created.json()["id"]

    running = client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "running"},
    )

    assert running.status_code == 200

    response = client.post(
        f"/tasks/{task_id}/execute",
        json={"operation": "market_research"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == ("Task cannot be claimed for execution")

    stored = client.get(f"/tasks/{task_id}")

    assert stored.status_code == 200
    assert stored.json()["status"] == "running"
    assert stored.json()["result"] is None


def test_update_status_transition_conflict_returns_409(
    client: TestClient,
) -> None:
    created = client.post(
        "/tasks",
        json={
            "title": "Research",
            "description": "Analyze market",
        },
    )

    assert created.status_code == 201
    task_id = created.json()["id"]

    with patch.object(
        TaskManager,
        "update_status",
        side_effect=TaskTransitionConflictError("Concurrent transition"),
    ):
        response = client.patch(
            f"/tasks/{task_id}/status",
            json={"status": "running"},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Task state changed during transition"}


def test_execute_transition_conflict_returns_409(
    client: TestClient,
) -> None:
    created = client.post(
        "/tasks",
        json={
            "title": "Research",
            "description": "Analyze market",
        },
    )

    assert created.status_code == 201
    task_id = created.json()["id"]

    with patch.object(
        TaskManager,
        "complete_task",
        side_effect=TaskTransitionConflictError("Concurrent transition"),
    ):
        response = client.post(
            f"/tasks/{task_id}/execute",
            json={"operation": "market_research"},
        )

    assert response.status_code == 409
    assert response.json() == {"detail": "Task state changed during transition"}
