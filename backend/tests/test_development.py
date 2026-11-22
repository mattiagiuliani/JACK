import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
import test_portfolio
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_execution_planning import planning, ready, review, scope
from test_portfolio import command, create

from app.agents.development import DevelopmentAgent, StaticPrototypeProvider
from app.db.session import get_db
from app.development.models import (
    MAX_FILE_BYTES,
    Bundle,
    DevelopmentRequest,
    SourceFile,
    canonical,
)
from app.development.router import workspace_root
from app.development.service import (
    ArtifactDB,
    DevelopmentContext,
    DevelopmentService,
)
from app.development.workspace import materialize, verify_workspace
from app.main import app
from app.portfolio.planning import PlanRecord
from app.portfolio.service import PortfolioConflict
from app.tasks.models import Task

client = test_portfolio.client


def approved(client: TestClient) -> tuple[dict, dict]:
    venture, decision = ready(client)
    result = planning(client, venture, decision)
    assert result.status_code == 201
    record = review(client, result.json()["audit"]["id"])
    assert record.status_code == 200
    return venture, record.json()


def request_for(source: dict) -> dict:
    return {
        "plan_id": source["audit"]["id"],
        "task_ids": ["t1"],
        "actor": "developer",
        "reason": "Prepare a local visual scaffold",
        "target": "static-prototype-v1",
    }


def generate(client: TestClient, request: dict, key="development"):
    return client.post(
        "/development-artifacts", json=request, headers={"Idempotency-Key": key}
    )


def export(client: TestClient, artifact: dict, actor="reviewer"):
    return client.post(
        f"/development-artifacts/{artifact['report']['id']}/export",
        json={"actor": actor, "reason": "Inspect prototype locally"},
    )


def engine_for_client():
    generator = app.dependency_overrides[get_db]()
    with next(generator) as session:
        engine = session.get_bind()
    generator.close()
    return engine


def test_generation_snapshot_idempotency_and_no_business_mutation(client, tmp_path):
    venture, source = approved(client)
    before = client.get(f"/ventures/{venture['id']}/history").json()
    tasks = client.get("/tasks").json()
    request = request_for(source)
    response = generate(client, request)
    assert response.status_code == 201
    artifact = response.json()
    assert artifact["report"]["source_plan"] == source
    bundle = Bundle.model_validate(artifact["report"]["bundle"])
    assert artifact["report"]["bundle_sha256"] == bundle.fingerprint()
    assert bundle.execution_authorized is False
    assert bundle.completion == "prototype_requires_review"
    assert {f.path for f in bundle.files} == {"index.html", "scope.json", "REVIEW.md"}
    assert generate(client, request).json() == artifact
    assert generate(client, {**request, "reason": "changed"}).status_code == 409
    url = f"/development-artifacts/{artifact['report']['id']}"
    assert client.get(url).json() == artifact
    assert client.get(f"/ventures/{venture['id']}/history").json() == before
    assert client.get("/tasks").json() == tasks
    assert list(tmp_path.glob("*/index.html")) == []
    assert export(client, artifact).status_code == 503


@pytest.mark.parametrize("outcome", [None, "rejected"])
def test_unapproved_plan_is_blocked(client, outcome):
    venture, decision = ready(client)
    source = planning(client, venture, decision).json()
    if outcome:
        assert review(client, source["audit"]["id"], outcome).status_code == 200
    assert generate(client, request_for(source)).status_code == 409
    with Session(engine_for_client()) as session:
        assert session.scalar(select(func.count()).select_from(ArtifactDB)) == 0


def test_hold_plan_cannot_generate(client):
    source = planning(client, create(client)).json()
    assert generate(client, request_for(source)).status_code == 409


@pytest.mark.parametrize("changed_venture", ["source", "other"])
def test_portfolio_freshness_blocks_new_work_but_preserves_history(
    client, tmp_path, changed_venture
):
    venture, source = approved(client)
    request = request_for(source)
    artifact = generate(client, request).json()
    app.dependency_overrides[workspace_root] = lambda: tmp_path / "workspaces"
    changed = (
        venture
        if changed_venture == "source"
        else next(v for v in client.get("/ventures").json() if v["id"] != venture["id"])
    )
    assert (
        command(
            client, changed, "pause", {"kind": "transition", "status": "paused"}
        ).status_code
        == 200
    )
    assert generate(client, request, "fresh-key").status_code == 409
    # A replay is a historical receipt, never a new generation or export.
    assert generate(client, request).json() == artifact
    assert export(client, artifact).status_code == 409
    assert not (tmp_path / "workspaces").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_plan",
        "unknown_task",
        "duplicate_task",
        "empty_tasks",
        "unknown_target",
        "extra",
        "missing_key",
        "blank_actor",
    ],
)
def test_invalid_development_requests(client, mutation):
    _, source = approved(client)
    request = request_for(source)
    expected = 422
    if mutation == "missing_plan":
        request["plan_id"] = str(uuid4())
        expected = 404
    elif mutation == "unknown_task":
        request["task_ids"] = ["does-not-exist"]
    elif mutation == "duplicate_task":
        request["task_ids"] = ["t1", "t1"]
    elif mutation == "empty_tasks":
        request["task_ids"] = []
    elif mutation == "unknown_target":
        request["target"] = "remote-ai"
    elif mutation == "extra":
        request["workspace"] = "C:/outside"
    elif mutation == "blank_actor":
        request["actor"] = " "
    response = (
        client.post("/development-artifacts", json=request)
        if mutation == "missing_key"
        else generate(client, request)
    )
    assert response.status_code == expected
    assert client.get(f"/development-artifacts/{uuid4()}").status_code == 404


def test_dependency_closure_and_stable_topological_order(client):
    venture, decision = ready(client)
    data = scope()
    data["tasks"].append(
        {
            **deepcopy(data["tasks"][0]),
            "id": "dependent",
            "dependencies": ["t1"],
            "estimated_cost": "0",
        }
    )
    response = client.post(
        "/execution-plans",
        headers={"Idempotency-Key": "plan"},
        json={
            "venture_id": venture["id"],
            "expected_version": venture["version"],
            "actor": "owner",
            "reason": "Ordered work",
            "decision_id": decision,
            "scope": data,
        },
    )
    assert response.status_code == 201
    source = review(client, response.json()["audit"]["id"]).json()
    request = {**request_for(source), "task_ids": ["dependent"]}
    assert generate(client, request).status_code == 422
    request["task_ids"] = ["dependent", "t1"]
    artifact = generate(client, request).json()
    assert artifact["report"]["bundle"]["task_order"] == ["t1", "dependent"]


def test_agent_is_deterministic_and_escapes_untrusted_html(client):
    _, source = approved(client)
    data = deepcopy(source)
    # Test the pure provider with adversarial display text, never execute it.
    data["audit"]["result"]["scope"]["objective"] = '<script>alert("x")</script>'
    context = DevelopmentContext(
        request=DevelopmentRequest.model_validate(request_for(data)),
        source_plan=PlanRecord.model_validate(data),
    )
    agent = DevelopmentAgent()
    task = Task(
        title="Prototype", description="Local only", result=context.model_dump_json()
    )
    before = task.model_dump()
    assert agent.execute(task) == agent.execute(task)
    bundle = Bundle.model_validate_json(agent.execute(task))
    page = next(f.content for f in bundle.files if f.path == "index.html")
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "Content-Security-Policy" in page
    assert task.model_dump() == before
    with pytest.raises(ValueError):
        agent.execute(Task(title="Empty", description="No context"))
    context_data = context.model_dump(mode="json")
    context_data["request"]["plan_id"] = str(uuid4())
    with pytest.raises(ValueError, match="Plan id"):
        agent.execute(task.model_copy(update={"result": json.dumps(context_data)}))


def test_export_receipt_manifest_replay_and_tamper_detection(client, tmp_path):
    _, source = approved(client)
    artifact = generate(client, request_for(source)).json()
    root = tmp_path / "workspaces"
    app.dependency_overrides[workspace_root] = lambda: root
    response = export(client, artifact)
    assert response.status_code == 200
    result = response.json()
    assert result["report"] == artifact["report"]
    target = Path(result["export"]["workspace"])
    assert target.parent == root
    bundle = Bundle.model_validate(result["report"]["bundle"])
    assert (target / "manifest.json").read_bytes() == canonical(
        bundle.manifest()
    ) + b"\n"
    verify_workspace(target, bundle)
    assert export(client, artifact).json() == result
    assert export(client, artifact, "another").status_code == 409
    assert not list(root.glob(".jack-*"))
    (target / "index.html").write_text("tampered", encoding="utf-8")
    assert export(client, artifact).status_code == 409
    assert (target / "index.html").read_text(encoding="utf-8") == "tampered"


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/absolute",
        "C:/absolute",
        "a\\b",
        "a//b",
        "./file",
        "CON",
        "con.txt",
        "nul",
        "LPT1.txt",
        "name.",
        "a/b.",
        ".env",
        "file:stream",
        "a/../b",
        "a/./b",
        "a\x00b",
        "x" * 81,
    ],
)
def test_reject_unsafe_artifact_paths(path):
    with pytest.raises(ValidationError):
        SourceFile(path=path, content="text\n")


def test_bundle_byte_limits_duplicates_and_reserved_manifest():
    with pytest.raises(ValidationError):
        SourceFile(path="a.txt", content="é" * MAX_FILE_BYTES)
    for content in ("x\x00y", "x\r\n"):
        with pytest.raises(ValidationError):
            SourceFile(path="a.txt", content=content)
    for names in (
        ("a.txt", "A.txt"),
        ("manifest.json",),
        ("a", "A/b.txt"),
        ("manifest.json/child",),
    ):
        with pytest.raises(ValidationError):
            Bundle(
                files=tuple(SourceFile(path=n, content="x") for n in names),
                task_order=("t1",),
            )
    with pytest.raises(ValidationError, match="byte limit"):
        Bundle(
            files=tuple(
                SourceFile(path=f"{i}.txt", content="x" * MAX_FILE_BYTES)
                for i in range(5)
            ),
            task_order=("t1",),
        )


def simple_bundle() -> Bundle:
    return Bundle(
        files=(SourceFile(path="a.txt", content="hello\n"),), task_order=("t1",)
    )


@pytest.mark.parametrize("damage", ["extra_file", "extra_dir", "missing", "manifest"])
def test_workspace_never_overwrites_conflicting_data(tmp_path, damage):
    bundle = simple_bundle()
    artifact_id = uuid4()
    target = materialize(tmp_path, artifact_id, bundle)
    if damage == "extra_file":
        (target / "unknown").write_text("keep", encoding="utf-8")
    elif damage == "extra_dir":
        (target / "unknown").mkdir()
    elif damage == "missing":
        (target / "a.txt").unlink()
    else:
        (target / "manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PortfolioConflict):
        materialize(tmp_path, artifact_id, bundle)


def test_partial_write_failure_cleans_staging(tmp_path, monkeypatch):
    original = Path.open

    def fail(path, *args, **kwargs):
        if path.name == "a.txt" and args and args[0] == "xb":
            raise OSError("Synthetic disk failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail)
    with pytest.raises(OSError):
        materialize(tmp_path, uuid4(), simple_bundle())
    assert list(tmp_path.iterdir()) == []


def test_links_never_escape_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    try:
        root.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        assert root.parent == tmp_path
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(root), str(outside)],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr.decode(errors="replace")
    with pytest.raises(PortfolioConflict, match="links"):
        materialize(root, uuid4(), simple_bundle())
    assert list(outside.iterdir()) == []


def test_concurrent_materialization_is_complete_and_identical(tmp_path):
    barrier = Barrier(2)
    artifact_id = uuid4()
    bundle = simple_bundle()

    def write(_):
        barrier.wait(timeout=10)
        return materialize(tmp_path, artifact_id, bundle)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, range(2)))
    assert results[0] == results[1]
    verify_workspace(results[0], bundle)
    assert not list(tmp_path.glob(".jack-*"))


def test_concurrent_creation_and_failed_export_receipt_recovery(
    client, tmp_path, monkeypatch
):
    _, source = approved(client)
    request = DevelopmentRequest.model_validate(request_for(source))
    engine = engine_for_client()
    barrier = Barrier(2)

    def write(_):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            try:
                return DevelopmentService(session).create("race", request).report.id
            except PortfolioConflict:
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, range(2)))
    with Session(engine) as session:
        record = DevelopmentService(session).create("race", request)
        assert any(r == record.report.id for r in results)
        assert session.scalar(select(func.count()).select_from(ArtifactDB)) == 1
        from sqlalchemy.exc import OperationalError

        from app.development.models import ExportRequest

        review_request = ExportRequest(actor="owner", reason="Inspect locally")
        original_commit = session.commit

        def fail():
            raise OperationalError("synthetic", {}, Exception("commit failed"))

        monkeypatch.setattr(session, "commit", fail)
        with pytest.raises(PortfolioConflict):
            DevelopmentService(session).export(
                record.report.id, review_request, tmp_path
            )
        target = tmp_path / str(record.report.id)
        verify_workspace(target, record.report.bundle)
        monkeypatch.setattr(session, "commit", original_commit)
        recovered = DevelopmentService(session).export(
            record.report.id, review_request, tmp_path
        )
        assert recovered.export is not None
        assert recovered.report == record.report


def test_export_uses_fixed_config_root_and_refuses_path_input(client, tmp_path):
    _, source = approved(client)
    artifact = generate(client, request_for(source)).json()
    root = tmp_path / "root"
    app.dependency_overrides[workspace_root] = lambda: root
    url = f"/development-artifacts/{artifact['report']['id']}/export"
    assert (
        client.post(
            url, json={"actor": "owner", "reason": "Inspect", "path": "../escape"}
        ).status_code
        == 422
    )
    assert export(client, artifact).status_code == 200
    app.dependency_overrides[workspace_root] = lambda: tmp_path / "changed"
    assert export(client, artifact).status_code == 409
    assert not (tmp_path / "changed").exists()


def test_provider_error_leaves_no_artifact_and_can_retry(client, monkeypatch):
    _, source = approved(client)
    request = request_for(source)
    original = StaticPrototypeProvider.generate

    def fail(self, source, request):
        raise ValueError("Synthetic provider failure")

    monkeypatch.setattr(StaticPrototypeProvider, "generate", fail)
    assert generate(client, request).status_code == 422
    with Session(engine_for_client()) as session:
        assert session.scalar(select(func.count()).select_from(ArtifactDB)) == 0
    monkeypatch.setattr(StaticPrototypeProvider, "generate", original)
    artifact = generate(client, request).json()
    replay = generate(client, request, "second-key").json()
    assert artifact["report"]["bundle"] == replay["report"]["bundle"]
    assert artifact["report"]["bundle_sha256"] == replay["report"]["bundle_sha256"]


def test_export_receipt_compare_and_swap_loser(client, tmp_path, monkeypatch):
    from sqlalchemy.sql.dml import Update

    from app.development.models import ExportRequest

    _, source = approved(client)
    artifact = generate(client, request_for(source)).json()
    artifact_id = UUID(artifact["report"]["id"])
    engine = engine_for_client()
    with Session(engine) as first, Session(engine) as second:
        original = first.execute
        winner = ExportRequest(actor="winner", reason="Reviewed locally")

        def intercept(statement, *args, **kwargs):
            if isinstance(statement, Update):
                DevelopmentService(second).export(artifact_id, winner, tmp_path)
            return original(statement, *args, **kwargs)

        monkeypatch.setattr(first, "execute", intercept)
        with pytest.raises(PortfolioConflict, match="Concurrent export"):
            DevelopmentService(first).export(
                artifact_id, ExportRequest(actor="loser", reason="Reviewed"), tmp_path
            )
        final = DevelopmentService(second).get(artifact_id)
        assert final.export is not None
        assert final.export.actor == "winner"
        assert final.report.model_dump(mode="json") == artifact["report"]


def test_migration_full_chain_and_existing_approved_plan(client, tmp_path, monkeypatch):
    from alembic.config import Config
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine, inspect

    from alembic import command as migrations
    from app.db import session as db_session

    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    monkeypatch.setattr(db_session, "DATABASE_URL", url)
    config = Config("alembic.ini")
    migrations.upgrade(config, "101_planning")
    engine = create_engine(url, connect_args={"check_same_thread": False})

    def database():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = database
    _, source = approved(client)
    migrations.upgrade(config, "head")
    with engine.connect() as connection:
        assert MigrationContext.configure(connection).get_current_revision() == (
            "102_development"
        )
        columns = inspect(connection).get_columns("development_artifacts")
        assert {c["name"] for c in columns} == set(ArtifactDB.__table__.columns.keys())
    artifact = generate(client, request_for(source)).json()
    app.dependency_overrides[workspace_root] = lambda: tmp_path / "artifacts"
    assert export(client, artifact).status_code == 200
    url_path = f"/execution-plans/{source['audit']['id']}"
    assert client.get(url_path).json() == source
    migrations.downgrade(config, "101_planning")
    with engine.connect() as connection:
        assert "development_artifacts" not in inspect(connection).get_table_names()
    assert client.get(url_path).json() == source
    migrations.upgrade(config, "head")
    assert generate(client, request_for(source)).status_code == 201
    engine.dispose()


def test_explicit_registry_workflow_and_artifact_integrity(client):
    from app.agents.base import Agent
    from app.agents.orchestrator import AgentOrchestrator
    from app.agents.registry import AgentRegistry
    from app.tasks.manager import TaskManager

    _, source = approved(client)
    context = DevelopmentContext(
        request=DevelopmentRequest.model_validate(request_for(source)),
        source_plan=PlanRecord.model_validate(source),
    )

    class SourceAgent(Agent):
        def execute(self, task):
            return context.model_dump_json()

    registry = AgentRegistry()
    registry.register("approved-context", SourceAgent())
    registry.register("development", DevelopmentAgent())
    manager = TaskManager()
    task = manager.create_task(title="Prototype", description="Generate only")
    result = AgentOrchestrator(manager, registry).execute_workflow(
        task.id, ["approved-context", "development"]
    )
    assert result.succeeded
    bundle = Bundle.model_validate_json(result.steps[-1].output or "")
    artifact = generate(client, request_for(source)).json()
    assert bundle.model_dump(mode="json") == artifact["report"]["bundle"]
    with Session(engine_for_client()) as session:
        row = session.get(ArtifactDB, artifact["report"]["id"])
        assert row is not None
        data = json.loads(row.report)
        data["bundle"]["files"][0]["content"] = "tampered\n"
        row.report = json.dumps(data)
        session.commit()
    assert (
        client.get(f"/development-artifacts/{artifact['report']['id']}").status_code
        == 409
    )
