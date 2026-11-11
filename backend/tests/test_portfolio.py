from collections.abc import Generator
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.portfolio.models import Command, Creation, Metric
from app.portfolio.service import PortfolioConflict, PortfolioService
from app.tasks.db_models import TaskDB  # noqa: F401

CREATE = {
    "actor": "owner",
    "reason": "Initial plan",
    "venture": {
        "name": "Demo",
        "description": "Demo topic",
        "currency": "EUR",
        "capital_limit": "100.000001",
        "budget": "80",
    },
}


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'portfolio.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    def db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def create(client: TestClient, key: str = "create") -> dict:
    response = client.post("/ventures", json=CREATE, headers={"Idempotency-Key": key})
    assert response.status_code == 201
    return response.json()


def command(
    client: TestClient,
    venture: dict,
    key: str,
    change: dict,
    version: int | None = None,
):
    return client.post(
        f"/ventures/{venture['id']}/commands",
        headers={"Idempotency-Key": key},
        json={
            "actor": "owner",
            "reason": "Manual record",
            "expected_version": version or venture["version"],
            "change": change,
        },
    )


def expense(amount: str = "30", ref: str = "invoice-1") -> dict:
    return {
        "kind": "expense",
        "amount": amount,
        "currency": "EUR",
        "incurred_at": "2026-11-11T10:00:00Z",
        "description": "Already incurred",
        "external_reference": ref,
    }


def test_multibusiness_persistence_and_idempotency(client: TestClient):
    first = create(client)
    assert create(client) == first
    second = create(client, "second")
    assert second["id"] != first["id"]
    assert len(client.get("/ventures").json()) == 2
    assert client.get(f"/ventures/{first['id']}").json() == first
    changed = {**CREATE, "reason": "different"}
    assert (
        client.post(
            "/ventures", json=changed, headers={"Idempotency-Key": "create"}
        ).status_code
        == 409
    )
    assert len(client.get(f"/ventures/{first['id']}/history").json()) == 1


def test_lifecycle_stale_version_and_retry(client: TestClient):
    venture = create(client)
    assert (
        command(
            client, venture, "invalid", {"kind": "transition", "status": "operating"}
        ).status_code
        == 409
    )
    response = command(
        client, venture, "research", {"kind": "transition", "status": "researching"}
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert (
        command(
            client, venture, "research", {"kind": "transition", "status": "researching"}
        ).json()
        == response.json()
    )
    assert (
        command(
            client, venture, "stale", {"kind": "transition", "status": "closed"}
        ).status_code
        == 409
    )
    closed = command(
        client, response.json(), "close", {"kind": "transition", "status": "closed"}
    ).json()
    assert (
        command(
            client, closed, "reopen", {"kind": "transition", "status": "idea"}
        ).status_code
        == 409
    )


def test_expenses_limits_atomicity_and_exact_decimal(client: TestClient):
    venture = create(client)
    first = command(client, venture, "expense", expense("30.000001"))
    assert first.status_code == 200
    venture = first.json()
    assert Decimal(venture["spent"]) == Decimal("30.000001")
    assert command(client, venture, "duplicate", expense()).status_code == 409
    assert (
        command(client, venture, "over", expense("50", "invoice-2")).status_code == 409
    )
    assert (
        command(
            client,
            venture,
            "low",
            {"kind": "limits", "budget": "30", "capital_limit": "100"},
        ).status_code
        == 409
    )
    assert (
        command(
            client, venture, "wrong-currency", {**expense(ref="usd"), "currency": "USD"}
        ).status_code
        == 422
    )
    assert client.get(f"/ventures/{venture['id']}").json() == venture
    history = client.get(f"/ventures/{venture['id']}/history").json()
    assert len(history) == 2
    assert history[-1]["request"]["change"]["external_reference"] == "invoice-1"
    assert history[-1]["actor"] == "owner"


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", "-1"),
        ("amount", "NaN"),
        ("amount", "0.0000001"),
        ("incurred_at", "2026-11-11T10:00:00"),
    ],
)
def test_invalid_expense(client: TestClient, field: str, value: str):
    venture = create(client)
    assert (
        command(client, venture, "invalid", {**expense(), field: value}).status_code
        == 422
    )


@pytest.mark.parametrize("basis", ["observed", "estimated"])
def test_metrics_persist_provenance(client: TestClient, basis: str):
    venture = create(client)
    metric = {
        "kind": "metric",
        "name": "revenue",
        "value": "12.34",
        "unit": "money",
        "currency": "EUR",
        "basis": basis,
        "source": "manual ledger",
        "methodology": "sum for period",
        "period_start": "2026-11-01T00:00:00Z",
        "period_end": "2026-11-11T00:00:00Z",
    }
    assert command(client, venture, "metric", metric).status_code == 200
    history = client.get(f"/ventures/{venture['id']}/history").json()
    assert history[-1]["request"]["change"] == metric
    assert history[-1]["result"]["spent"] == "0"
    with pytest.raises(ValidationError):
        Metric.model_validate({**metric, "currency": None})
    with pytest.raises(ValidationError):
        Metric.model_validate({**metric, "period_end": "2026-01-01T00:00:00Z"})


def test_missing_and_required_key(client: TestClient):
    assert client.post("/ventures", json=CREATE).status_code == 422
    assert client.get(f"/ventures/{uuid4()}").status_code == 404
    assert client.get(f"/ventures/{uuid4()}/history").status_code == 404


def test_separate_sessions_reject_stale_update(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as a, Session(engine) as b:
        first = PortfolioService(a).apply("create", Creation.model_validate(CREATE))
        stale = PortfolioService(b).get(first.id)
        request = Command.model_validate(
            {
                "actor": "owner",
                "reason": "review",
                "expected_version": stale.version,
                "change": {"kind": "transition", "status": "researching"},
            }
        )
        PortfolioService(a).apply("winner", request, first.id)
        with pytest.raises(PortfolioConflict):
            PortfolioService(b).apply("loser", request, first.id)
        assert len(PortfolioService(b).history(first.id)) == 2
    engine.dispose()


def test_assessment_links_verified_workflow_and_preserves_snapshot(client: TestClient):
    from app.agents import (
        AgentOrchestrator,
        AgentRegistry,
        BusinessResearchAgent,
        BusinessValidationAgent,
        ControlledResearchProvider,
        ValidationReport,
    )
    from app.agents.research_corpus import DEMO_TOPIC
    from app.tasks.manager import TaskManager
    from app.tasks.repository import TaskRepository

    db = app.dependency_overrides[get_db]()
    with next(db) as session:
        manager = TaskManager(TaskRepository(session))
        registry = AgentRegistry()
        registry.register(
            "research", BusinessResearchAgent(ControlledResearchProvider())
        )
        registry.register("validation", BusinessValidationAgent())
        task = manager.create_task(title="Validate", description=DEMO_TOPIC)
        workflow = AgentOrchestrator(manager, registry).execute_workflow(
            task.id, ["research", "validation"]
        )
        assert workflow.steps[-1].output is not None
        report = ValidationReport.model_validate_json(workflow.steps[-1].output)
    db.close()
    request = {**CREATE, "venture": {**CREATE["venture"], "description": DEMO_TOPIC}}
    venture = client.post(
        "/ventures", json=request, headers={"Idempotency-Key": "linked"}
    ).json()
    change = {
        "kind": "assessment",
        "task_id": str(task.id),
        "report": report.model_dump(mode="json"),
        "evidence_ids": ["demo-1"],
    }
    assert (
        command(
            client, venture, "missing-task", {**change, "task_id": str(uuid4())}
        ).status_code
        == 422
    )
    altered = report.model_dump(mode="json")
    altered["recommendation"]["rationale"] = "Different assessment"
    assert (
        command(client, venture, "altered", {**change, "report": altered}).status_code
        == 422
    )
    assert (
        command(
            client, venture, "unknown-evidence", {**change, "evidence_ids": ["missing"]}
        ).status_code
        == 422
    )
    result = command(client, venture, "assessment", change)
    assert result.status_code == 200
    assert result.json()["status"] == "idea"
    history = client.get(f"/ventures/{venture['id']}/history").json()
    assert history[-1]["request"]["change"]["report"] == change["report"]


def test_capital_and_budget_validation(client: TestClient):
    request = {**CREATE, "venture": {**CREATE["venture"], "budget": "101"}}
    assert (
        client.post(
            "/ventures", json=request, headers={"Idempotency-Key": "bad"}
        ).status_code
        == 422
    )
    venture = create(client)
    response = command(
        client,
        venture,
        "raise",
        {"kind": "limits", "capital_limit": "200", "budget": "150"},
    )
    assert response.status_code == 200
    assert response.json()["budget"] == "150"
    assert (
        command(
            client,
            response.json(),
            "bad-limits",
            {"kind": "limits", "capital_limit": "100", "budget": "150"},
        ).status_code
        == 422
    )


def test_migration_upgrade_and_downgrade(tmp_path: Path):
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = Path(__file__).parents[1] / "alembic/versions/097_portfolio.py"
    spec = importlib.util.spec_from_file_location("portfolio_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        Base.metadata.tables["tasks"].create(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert {"tasks", "ventures", "portfolio_events"} == set(
                inspect(connection).get_table_names()
            )
            migration.downgrade()
            assert inspect(connection).get_table_names() == ["tasks"]
    engine.dispose()


def test_pause_resumes_prior_stage(client: TestClient):
    venture = create(client)
    research = command(
        client, venture, "research", {"kind": "transition", "status": "researching"}
    ).json()
    paused = command(
        client, research, "pause", {"kind": "transition", "status": "paused"}
    ).json()
    assert paused["paused_from"] == "researching"
    assert (
        command(
            client, paused, "skip", {"kind": "transition", "status": "operating"}
        ).status_code
        == 409
    )
    resumed = command(
        client, paused, "resume", {"kind": "transition", "status": "researching"}
    )
    assert resumed.status_code == 200
    assert resumed.json()["paused_from"] is None


def test_compare_and_swap_loser_has_no_event(tmp_path: Path, monkeypatch):
    from sqlalchemy.sql.dml import Update

    engine = create_engine(f"sqlite:///{tmp_path / 'cas.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as a, Session(engine) as b:
        venture = PortfolioService(a).apply("create", Creation.model_validate(CREATE))
        request = Command.model_validate(
            {
                "actor": "owner",
                "reason": "review",
                "expected_version": 1,
                "change": {"kind": "transition", "status": "researching"},
            }
        )
        original = a.execute

        def intercept(statement, *args, **kwargs):
            if isinstance(statement, Update):
                PortfolioService(b).apply("winner", request, venture.id)
            return original(statement, *args, **kwargs)

        monkeypatch.setattr(a, "execute", intercept)
        with pytest.raises(PortfolioConflict, match="Concurrent venture update"):
            PortfolioService(a).apply("loser", request, venture.id)
        events = PortfolioService(b).history(venture.id)
        assert len(events) == 2
        assert events[-1].result.version == 2
        assert (
            PortfolioService(b).apply("winner", request, venture.id)
            == events[-1].result
        )
    engine.dispose()
