from copy import deepcopy
from decimal import Decimal

import pytest
import test_portfolio
from pydantic import ValidationError
from test_portfolio import command, create
from test_portfolio_decisions import post, prepare, request_for, supported_report

from app.agents.execution_planner import Scope

client = test_portfolio.client


def scope():
    return {
        "objective": "Proposed minimal workflow",
        "requirements": [
            {
                "id": "r1",
                "description": "Minimal input workflow",
                "acceptance_criteria": ["Valid input produces a saved record"],
            }
        ],
        "tasks": [
            {
                "id": "t1",
                "requirement_ids": ["r1"],
                "deliverable": "Local prototype and verification report",
                "acceptance_criteria": ["Invalid input is rejected"],
                "dependencies": [],
                "priority": "high",
                "priority_reason": "Tests core feasibility before expansion",
                "estimated_hours": "8",
                "estimated_cost": "10",
                "estimate_basis": "Owner proposal; requires verification",
                "assumptions": ["Existing runtime can be reused"],
                "owner_role": "Developer",
                "checkpoint": "Human prototype review",
            }
        ],
        "risks": [
            {
                "description": "Runtime incompatibility",
                "mitigation": "Review dependencies first",
                "stop_rule": "Stop if ceiling cannot be met",
            }
        ],
        "exclusions": ["Public release"],
        "assumptions": ["Scope remains minimal"],
        "cost_limit": "20",
        "contingency": "5",
        "cost_basis": "Unverified estimate",
    }


def planning(client, venture, decision=None, key="plan"):
    return client.post(
        "/execution-plans",
        headers={"Idempotency-Key": key},
        json={
            "venture_id": venture["id"],
            "expected_version": venture["version"],
            "actor": "owner",
            "reason": "Plan only",
            "decision_id": decision,
            "scope": scope(),
        },
    )


def review(client, plan_id, outcome="approved"):
    return client.post(
        f"/execution-plans/{plan_id}/review",
        json={
            "actor": "owner",
            "reason": "Reviewed scope and assumptions",
            "outcome": outcome,
        },
    )


def ready(client):
    a = prepare(client, "a", supported_report())
    b = prepare(client, "b", supported_report())
    decision = post(client, request_for(a, b, cost="20")).json()["report"]["id"]
    assert (
        client.post(
            f"/portfolio-decisions/{decision}/review",
            json={
                "actor": "owner",
                "reason": "Read advice",
                "outcome": "acknowledged",
            },
        ).status_code
        == 200
    )
    return a, decision


def test_ready_persistence_review_and_no_side_effects(client):
    a, decision = ready(client)
    before = client.get(f"/ventures/{a['id']}/history").json()
    tasks_before = client.get("/tasks").json()
    response = planning(client, a, decision)
    assert response.status_code == 201
    record = response.json()
    result = record["audit"]["result"]
    assert result["outcome"] == "ready_for_review"
    assert Decimal(result["estimated_total_cost"]) == 15
    assert result["execution_authorized"] is False
    assert result["task_order"] == ["t1"]
    assert Decimal(result["estimated_total_hours"]) == 8
    assert record["review"] is None
    assert planning(client, a, decision).json() == record
    plan_id = record["audit"]["id"]
    assert client.get(f"/execution-plans/{plan_id}").json() == record
    approved = review(client, plan_id)
    assert approved.status_code == 200
    assert review(client, plan_id).json() == approved.json()
    assert review(client, plan_id, "rejected").status_code == 409
    assert client.get(f"/ventures/{a['id']}/history").json() == before
    assert client.get("/tasks").json() == tasks_before


def test_holds_missing_decision_stale_and_key_conflict(client):
    a = create(client)
    record = planning(client, a).json()
    assert record["audit"]["result"]["outcome"] == "hold"
    assert record["audit"]["result"]["scope"] is None
    assert review(client, record["audit"]["id"]).status_code == 409
    changed = command(
        client,
        a,
        "advance",
        {
            "kind": "transition",
            "status": "researching",
        },
    ).json()
    assert planning(client, changed).status_code == 409
    assert planning(client, a, key="stale").status_code == 409
    assert (
        client.get("/execution-plans/00000000-0000-0000-0000-000000000001").status_code
        == 404
    )


def test_stale_approval_and_decision(client):
    a, decision = ready(client)
    record = planning(client, a, decision).json()
    changed = command(
        client,
        a,
        "pause",
        {
            "kind": "transition",
            "status": "paused",
        },
    ).json()
    assert review(client, record["audit"]["id"]).status_code == 409
    assert (
        planning(client, changed, decision, "new").json()["audit"]["result"]["outcome"]
        == "hold"
    )


@pytest.mark.parametrize(
    "mutation", ["cycle", "unknown", "duplicate", "uncovered", "cost", "nan"]
)
def test_reject_invalid_scope(mutation):
    data = deepcopy(scope())
    if mutation == "cycle":
        data["tasks"][0]["dependencies"] = ["t1"]
    elif mutation == "unknown":
        data["tasks"][0]["dependencies"] = ["missing"]
    elif mutation == "duplicate":
        data["tasks"].append(deepcopy(data["tasks"][0]))
    elif mutation == "uncovered":
        data["requirements"].append({**data["requirements"][0], "id": "r2"})
    elif mutation == "cost":
        data["cost_limit"] = "1"
    else:
        data["tasks"][0]["estimated_cost"] = "NaN"
    with pytest.raises(ValidationError):
        Scope.model_validate(data)


def test_agent_experiment_and_determinism(client):
    from app.agents.execution_planner import (
        ExecutionPlannerAgent,
        PlanningContext,
        PlanningRequest,
        plan,
    )
    from app.agents.orchestrator import AgentOrchestrator
    from app.agents.registry import AgentRegistry
    from app.portfolio.models import Venture
    from app.tasks.manager import TaskManager

    a = prepare(client, "validation-missing")
    context = PlanningContext(
        request=PlanningRequest.model_validate(
            {
                "venture_id": a["id"],
                "expected_version": a["version"],
                "actor": "owner",
                "reason": "test",
                "scope": scope(),
            }
        ),
        venture=Venture.model_validate(a),
        history=(),
        validation=None,
        decision_clear=True,
    )
    assert plan(context).outcome == "experiment"
    assert plan(context) == plan(context)
    agent = ExecutionPlannerAgent()
    registry = AgentRegistry()
    registry.register("planner", agent)
    manager = TaskManager()
    task = manager.create_task(title="Plan", description="Plan only")
    # The explicit coordinator passes prior output to the planner.
    from app.agents.base import Agent

    class ContextAgent(Agent):
        def execute(self, task):
            return context.model_dump_json()

    registry.register("context", ContextAgent())
    result = AgentOrchestrator(manager, registry).execute_workflow(
        task.id, ["context", "planner"]
    )
    assert result.succeeded
    assert '"outcome":"experiment"' in (result.steps[-1].output or "")


def test_migration_roundtrip_preserves_prior_data(tmp_path, monkeypatch):
    import json
    import sqlite3

    from alembic.config import Config

    from alembic import command as migration
    from app.db import session as db_session

    path = tmp_path / "migration.db"
    monkeypatch.setattr(db_session, "DATABASE_URL", f"sqlite:///{path.as_posix()}")
    config = Config("alembic.ini")
    migration.upgrade(config, "098_decisions")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO portfolio_decisions(id,key,request,report) VALUES(?,?,?,?)",
            ("sentinel", "sentinel", json.dumps({}), json.dumps({})),
        )
        db.commit()
    migration.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM execution_plans").fetchone() == (0,)
    migration.downgrade(config, "098_decisions")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id FROM portfolio_decisions").fetchone() == (
            "sentinel",
        )
        assert (
            db.execute(
                "SELECT name FROM sqlite_master WHERE name='execution_plans'"
            ).fetchone()
            is None
        )
    migration.upgrade(config, "head")


def test_concurrent_creation_same_key(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import Session

    from app.agents.execution_planner import PlanningRequest
    from app.db.session import get_db
    from app.main import app
    from app.portfolio.planning import PlanningService
    from app.portfolio.service import PortfolioConflict

    a = create(client)
    request = PlanningRequest.model_validate(
        {
            "venture_id": a["id"],
            "expected_version": a["version"],
            "actor": "owner",
            "reason": "Concurrent plan",
            "scope": scope(),
        }
    )
    generator = app.dependency_overrides[get_db]()
    with next(generator) as session:
        engine = session.get_bind()
    generator.close()
    barrier = Barrier(2)

    def write():
        with Session(engine) as session:
            barrier.wait(timeout=10)
            try:
                return PlanningService(session).create("concurrent", request).audit.id
            except PortfolioConflict:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: write(), range(2)))
    with Session(engine) as session:
        record = PlanningService(session).create("concurrent", request)
    assert any(result == record.audit.id for result in results)
    assert all(result in (None, record.audit.id) for result in results)


def test_concurrent_review_is_single_immutable_result(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import Session

    from app.db.session import get_db
    from app.main import app
    from app.portfolio.planning import PlanningService, PlanReview
    from app.portfolio.service import PortfolioConflict

    a, decision = ready(client)
    record = planning(client, a, decision).json()
    from uuid import UUID

    plan_id = UUID(record["audit"]["id"])
    generator = app.dependency_overrides[get_db]()
    with next(generator) as session:
        engine = session.get_bind()
    generator.close()
    barrier = Barrier(2)

    def write(outcome):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            try:
                return PlanningService(session).review(
                    plan_id,
                    PlanReview.model_validate(
                        {
                            "actor": "owner",
                            "reason": "Concurrent review",
                            "outcome": outcome,
                        }
                    ),
                )
            except PortfolioConflict:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ["approved", "rejected"]))
    assert sum(result is not None for result in results) == 1
    with Session(engine) as session:
        final = PlanningService(session).get(plan_id)
    assert final in results


def test_other_portfolio_changes_block(client):
    a, decision = ready(client)
    record = planning(client, a, decision).json()
    # Changing any venture in the source comparison invalidates approval.
    others = [v for v in client.get("/ventures").json() if v["id"] != a["id"]]
    command(
        client, others[0], "pause-other", {"kind": "transition", "status": "paused"}
    )
    assert review(client, record["audit"]["id"]).status_code == 409
    result = planning(client, a, decision, "fresh-plan").json()
    assert result["audit"]["result"]["outcome"] == "hold"


def test_dependency_order_precedes_declared_priority(client):
    from app.agents.execution_planner import PlanningContext, plan

    a, decision = ready(client)
    record = planning(client, a, decision).json()
    context = record["audit"]["context"]
    data = context["request"]["scope"]
    second = deepcopy(data["tasks"][0])
    second.update(id="dependent", dependencies=["t1"], estimated_cost="0")
    data["tasks"][0]["priority"] = "low"
    data["tasks"] = [second, data["tasks"][0]]
    result = plan(PlanningContext.model_validate(context))
    assert result.task_order == ("t1", "dependent")
    assert result.estimated_total_hours == 16


def test_decision_cost_must_cover_plan_ceiling(client):
    a = prepare(client, "a", supported_report())
    b = prepare(client, "b", supported_report())
    decision = post(client, request_for(a, b, cost="10")).json()["report"]["id"]
    client.post(
        f"/portfolio-decisions/{decision}/review",
        json={
            "actor": "owner",
            "reason": "Read advice",
            "outcome": "acknowledged",
        },
    )
    result = planning(client, a, decision).json()["audit"]["result"]
    assert result["outcome"] == "hold"
    assert result["scope"] is None
