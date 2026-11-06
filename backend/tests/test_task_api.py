import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.tasks.manager import TaskManager


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    fresh_manager = TaskManager()

    monkeypatch.setattr(
        "app.tasks.router.task_manager",
        fresh_manager,
    )

    return TestClient(app)


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
