from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
import test_portfolio
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from test_business_validation import run
from test_portfolio import CREATE, command, create, expense

from app.agents.orchestrator import AgentResult, WorkflowResult
from app.agents.validation import ValidationReport
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.portfolio.decisions import DecisionDB, DecisionService, Review
from app.portfolio.models import Creation
from app.portfolio.service import PortfolioConflict, PortfolioService
from app.tasks.db_models import TaskDB

PERIOD = {"period_start": "2026-10-01T00:00:00Z", "period_end": "2026-10-31T00:00:00Z"}
CRITERION = {
    "name": "profit",
    "unit": "money",
    "currency": "EUR",
    **PERIOD,
    "minimum": "10",
    "rationale": "Owner-defined minimum for this test period",
}
METRIC = {
    "kind": "metric",
    **PERIOD,
    "name": "profit",
    "unit": "money",
    "currency": "EUR",
    "value": "20",
    "basis": "observed",
    "source": "Reviewed ledger",
    "methodology": "Revenue minus all recorded costs",
}


client = test_portfolio.client


def request_for(*ventures: dict, cost: str = "10") -> dict:
    return {
        "actor": "owner",
        "reason": "Compare next experiments",
        "candidates": [
            {
                "venture_id": v["id"],
                "expected_version": v["version"],
                "proposed_cost": cost,
            }
            for v in ventures
        ],
        "criteria": [CRITERION],
        "available_capital": {"EUR": "100"},
    }


def post(client: TestClient, request: dict, key: str = "decision"):
    return client.post(
        "/portfolio-decisions", json=request, headers={"Idempotency-Key": key}
    )


def supported_report() -> ValidationReport:
    _, report = run(True)
    data = report.model_dump(mode="json")
    for assessment in data["assessments"]:
        assessment.update(
            status="supported",
            confidence="corroborated",
            confidence_basis="Reviewed direct results (synthetic test only)",
            supporting=[
                {
                    "evidence_id": "demand_signal:1",
                    "interpretation": "Synthetic direct observation",
                }
            ],
            missing_data=[],
        )
    data["recommendation"] = {
        "action": "proceed",
        "rationale": "Synthetic reviewed validation",
        "requires_human_review": True,
    }
    return ValidationReport.model_validate(data)


def prepare(
    client: TestClient,
    key: str,
    report: ValidationReport | None = None,
    basis: str = "observed",
    value: str = "20",
) -> dict:
    venture = create(client, key)
    for state in ("researching", "validating", "experimenting", "operating"):
        venture = command(
            client, venture, f"{key}-{state}", {"kind": "transition", "status": state}
        ).json()
    venture = command(
        client, venture, f"{key}-metric", {**METRIC, "basis": basis, "value": value}
    ).json()
    if report:
        # Persist a completed synthetic workflow to exercise the real link validation.
        data = report.model_dump(mode="json")
        data["research"]["topic"] = venture["description"]
        report = ValidationReport.model_validate(data)
        task_id = uuid4()
        workflow = WorkflowResult(
            task_id=task_id,
            succeeded=True,
            steps=(AgentResult(agent="validation", output=report.model_dump_json()),),
        )
        db = app.dependency_overrides[get_db]()
        with next(db) as session:
            session.add(
                TaskDB(
                    id=str(task_id),
                    title="Synthetic reviewed results",
                    description=venture["description"],
                    status="completed",
                    result=workflow.model_dump_json(),
                )
            )
            session.commit()
        db.close()
        response = command(
            client,
            venture,
            f"{key}-assessment",
            {
                "kind": "assessment",
                "task_id": str(task_id),
                "report": report.model_dump(mode="json"),
                "evidence_ids": [e.id for e in report.research.evidence],
            },
        )
        assert response.status_code == 200
        venture = response.json()
    return venture


def test_abstention_idempotency_snapshot_and_review(client: TestClient):
    a, b = create(client, "a"), create(client, "b")
    request = request_for(a, b)
    response = post(client, request)
    assert response.status_code == 201
    record = response.json()
    report = record["report"]
    assert [r["action"] for r in report["recommendations"]] == ["abstain", "abstain"]
    assert all(r["missing_data"] for r in report["recommendations"])
    assert post(client, request).json() == record
    assert post(client, {**request, "reason": "different"}).status_code == 409
    url = f"/portfolio-decisions/{report['id']}"
    review = {"actor": "reviewer", "reason": "Need more data", "outcome": "rejected"}
    result = client.post(url + "/review", json=review)
    assert result.status_code == 200
    assert client.post(url + "/review", json=review).json() == result.json()
    assert (
        client.post(
            url + "/review", json={**review, "outcome": "acknowledged"}
        ).status_code
        == 409
    )
    updated = command(
        client, a, "update", {"kind": "transition", "status": "researching"}
    )
    assert updated.status_code == 200
    assert client.get(url).json()["report"] == report
    assert post(client, request, "stale").status_code == 409
    assert client.get(f"/ventures/{b['id']}").json() == b


@pytest.mark.parametrize(
    "basis,value,cost,expected",
    [
        ("observed", "20", "10", "expand"),
        ("observed", "20", "0", "maintain"),
        ("estimated", "200", "10", "abstain"),
        ("observed", "5", "10", "investigate"),
        ("observed", "20", "81", "suspend"),
    ],
)
def test_rules_and_comparison(
    client: TestClient, basis: str, value: str, cost: str, expected: str
):
    a = prepare(client, "a", supported_report(), basis, value)
    b = prepare(client, "b", supported_report())
    response = post(client, request_for(a, b, cost=cost))
    assert response.status_code == 201
    report = response.json()["report"]
    assert report["recommendations"][0]["action"] == expected
    assert str(a["id"]) in report["comparisons"][-1]
    assert str(b["id"]) in report["comparisons"][-1]
    assert "estimated" in report["comparisons"][-1]
    assert report["histories"][0][-1]["result"] == a
    assert client.get(f"/ventures/{a['id']}").json() == a
    assert client.get(f"/ventures/{b['id']}").json() == b


def test_shared_capital_unknown_currency_and_incomparable_metrics(client: TestClient):
    a = prepare(client, "a", supported_report())
    b = prepare(client, "b", supported_report())
    request = request_for(a, b, cost="60")
    result = post(client, request).json()["report"]
    assert all(r["action"] == "suspend" for r in result["recommendations"])
    request["available_capital"] = {}
    request["candidates"][0]["proposed_cost"] = "10"
    request["candidates"][1]["proposed_cost"] = "10"
    assert all(
        r["action"] == "abstain"
        for r in post(client, request, "unknown").json()["report"]["recommendations"]
    )
    request["available_capital"] = {"EUR": "100"}
    request["criteria"] = [{**CRITERION, "currency": "USD"}]
    result = post(client, request, "currency").json()["report"]
    assert all(r["action"] == "abstain" for r in result["recommendations"])
    request["criteria"] = [{**CRITERION, "period_end": "2026-11-01T00:00:00Z"}]
    assert (
        post(client, request, "period").json()["report"]["recommendations"][0]["action"]
        == "abstain"
    )


def test_duplicate_kpi_and_stale_review(client: TestClient):
    a = prepare(client, "a", supported_report())
    b = prepare(client, "b", supported_report())
    record = post(client, request_for(a, b)).json()
    a = command(client, a, "duplicate-kpi", METRIC).json()
    review = client.post(
        f"/portfolio-decisions/{record['report']['id']}/review",
        json={"actor": "owner", "reason": "Reviewed", "outcome": "acknowledged"},
    )
    assert review.status_code == 409
    assert (
        post(client, request_for(a, b), "new").json()["report"]["recommendations"][0][
            "action"
        ]
        == "abstain"
    )


@pytest.mark.parametrize(
    "mutation", ["duplicate", "empty", "negative", "naive", "unknown", "nonfinite"]
)
def test_invalid_requests(client: TestClient, mutation: str):
    a, b = create(client, "a"), create(client, "b")
    request = deepcopy(request_for(a, b))
    if mutation == "duplicate":
        request["candidates"][1] = request["candidates"][0]
    elif mutation == "empty":
        request["criteria"] = []
    elif mutation == "negative":
        request["candidates"][0]["proposed_cost"] = "-1"
    elif mutation == "naive":
        request["criteria"][0]["period_start"] = "2026-10-01T00:00:00"
    elif mutation == "unknown":
        request["auto_execute"] = True
    else:
        request["available_capital"]["EUR"] = "NaN"
    assert post(client, request).status_code == 422


def test_missing_decision_and_venture(client: TestClient):
    assert client.get(f"/portfolio-decisions/{uuid4()}").status_code == 404
    a, b = create(client, "a"), create(client, "b")
    request = request_for(a, b)
    request["candidates"][0]["venture_id"] = str(uuid4())
    assert post(client, request).status_code == 404
    assert client.post("/portfolio-decisions", json=request).status_code == 422


def test_review_compare_and_swap_loser(tmp_path: Path, monkeypatch):
    from sqlalchemy.sql.dml import Update

    from app.portfolio.decisions import DecisionRequest

    engine = create_engine(f"sqlite:///{tmp_path / 'reviews.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as a, Session(engine) as b:
        portfolio = PortfolioService(a)
        ventures = [
            portfolio.apply(key, Creation.model_validate(CREATE)) for key in ("a", "b")
        ]
        request = DecisionRequest.model_validate(
            request_for(*(v.model_dump(mode="json") for v in ventures))
        )
        record = DecisionService(a).create("decision", request)
        review = Review(actor="owner", reason="Reviewed", outcome="acknowledged")
        original = a.execute

        def intercept(statement, *args, **kwargs):
            if isinstance(statement, Update):
                DecisionService(b).review(record.report.id, review)
            return original(statement, *args, **kwargs)

        monkeypatch.setattr(a, "execute", intercept)
        with pytest.raises(PortfolioConflict, match="Concurrent review"):
            DecisionService(a).review(record.report.id, review)
        assert DecisionService(b).get(record.report.id).review is not None
        stored = b.get(DecisionDB, str(record.report.id))
        assert stored is not None
        assert stored.report == record.report.model_dump_json()
    engine.dispose()


def test_decision_migration_roundtrip(tmp_path: Path, monkeypatch):
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import inspect

    from alembic import command as migrations
    from app.db import session as db_session

    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setattr(db_session, "DATABASE_URL", url)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    migrations.upgrade(config, "097_portfolio")
    engine = create_engine(url)
    with Session(engine) as session:
        service = PortfolioService(session)
        ventures = [
            service.apply(key, Creation.model_validate(CREATE)) for key in ("a", "b")
        ]
    migrations.upgrade(config, "098_decisions")
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == (
            "098_decisions"
        )
        assert "portfolio_decisions" in inspect(connection).get_table_names()
    with Session(engine) as session:
        from app.portfolio.decisions import DecisionRequest

        record = DecisionService(session).create(
            "migrated",
            DecisionRequest.model_validate(
                request_for(*(v.model_dump(mode="json") for v in ventures))
            ),
        )
    with Session(engine) as session:
        assert DecisionService(session).get(record.report.id) == record
    migrations.downgrade(config, "097_portfolio")
    with engine.connect() as connection:
        assert "portfolio_decisions" not in inspect(connection).get_table_names()
    with Session(engine) as session:
        assert PortfolioService(session).list_all() == sorted(
            ventures, key=lambda v: str(v.id)
        )
    migrations.upgrade(config, "098_decisions")
    engine.dispose()


@pytest.mark.parametrize("status", ["paused", "closed"])
def test_inactive_venture_requires_new_human_plan(client: TestClient, status: str):
    a = prepare(client, "a", supported_report())
    b = prepare(client, "b", supported_report())
    a = command(client, a, "inactive", {"kind": "transition", "status": status}).json()
    record = post(client, request_for(a, b)).json()
    assert record["report"]["recommendations"][0]["action"] == "abstain"
    assert client.get(f"/ventures/{a['id']}").json() == a


def test_spent_capital_and_review_never_allocate(client: TestClient):
    a = prepare(client, "a", supported_report())
    b = prepare(client, "b", supported_report())
    a = command(client, a, "spent", expense("75")).json()
    record = post(client, request_for(a, b)).json()
    assert record["report"]["recommendations"][0]["action"] == "suspend"
    url = f"/portfolio-decisions/{record['report']['id']}/review"
    reviewed = client.post(
        url, json={"actor": "owner", "reason": "Checked", "outcome": "acknowledged"}
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["report"] == record["report"]
    assert client.get(f"/ventures/{a['id']}").json() == a
    assert client.get(f"/ventures/{b['id']}").json() == b


@pytest.mark.parametrize("external", [False, True])
def test_unvalidated_reports_cannot_support_expansion(client: TestClient, external):
    _, report = run(external)
    a = prepare(client, "a", report)
    b = prepare(client, "b", report)
    result = post(client, request_for(a, b)).json()["report"]
    assert all(r["action"] == "abstain" for r in result["recommendations"])


def test_corroborated_rejection_is_preserved(client: TestClient):
    data = supported_report().model_dump(mode="json")
    assessment = data["assessments"][0]
    assessment.update(
        status="contradicted", opposing=assessment["supporting"], supporting=[]
    )
    data["recommendation"].update(
        action="reject", rationale="Observed contrary results"
    )
    report = ValidationReport.model_validate(data)
    a = prepare(client, "a", report)
    b = prepare(client, "b", supported_report())
    result = post(client, request_for(a, b)).json()["report"]
    assert result["recommendations"][0]["action"] == "suspend"
    assert any("reject" in r for r in result["recommendations"][0]["reasons"])


def test_future_observations_require_abstention(client: TestClient):
    a = prepare(client, "a", supported_report())
    b = prepare(client, "b", supported_report())
    future = {
        "period_start": "2099-01-01T00:00:00Z",
        "period_end": "2099-02-01T00:00:00Z",
    }
    a = command(client, a, "future", {**METRIC, **future}).json()
    request = request_for(a, b)
    request["criteria"] = [{**CRITERION, **future}]
    result = post(client, request).json()["report"]["recommendations"][0]
    assert result["action"] == "abstain"
    assert any("not ended" in m for m in result["missing_data"])


def test_currencies_are_never_converted_or_pooled(client: TestClient):
    a = prepare(client, "a", supported_report())
    payload = deepcopy(CREATE)
    payload["venture"]["currency"] = "USD"
    response = client.post(
        "/ventures", json=payload, headers={"Idempotency-Key": "usd"}
    )
    assert response.status_code == 201
    b = response.json()
    request = request_for(a, b, cost="60")
    request["available_capital"] = {"EUR": "60", "USD": "60"}
    result = post(client, request).json()["report"]
    assert result["recommendations"][0]["action"] == "expand"
    assert result["recommendations"][1]["action"] == "abstain"
    assert result["comparisons"][0].startswith("EUR: total proposed cost 60;")
    assert result["comparisons"][1].startswith("USD: total proposed cost 60;")


def test_provisional_support_requires_investigation(client: TestClient):
    data = supported_report().model_dump(mode="json")
    data["assessments"][0]["confidence"] = "limited"
    data["recommendation"]["action"] = "experiment"
    report = ValidationReport.model_validate(data)
    a = prepare(client, "a", report)
    b = prepare(client, "b", supported_report())
    result = post(client, request_for(a, b)).json()["report"]
    assert result["recommendations"][0]["action"] == "investigate"
