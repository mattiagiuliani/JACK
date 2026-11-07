from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


def test_startup_recovery_disabled_by_default(
    monkeypatch,
) -> None:
    monkeypatch.delenv("JACK_RECOVER_ON_STARTUP", raising=False)

    with patch("app.main.recover_tasks_on_startup") as recover:
        with TestClient(app) as client:
            response = client.get("/health")

        assert response.status_code == 200
        recover.assert_not_called()


def test_startup_recovery_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("JACK_RECOVER_ON_STARTUP", "1")

    with patch("app.main.recover_tasks_on_startup") as recover:
        recover.return_value = []

        with TestClient(app) as client:
            response = client.get("/health")

        assert response.status_code == 200
        recover.assert_called_once_with()
