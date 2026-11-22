"""Deterministic static prototype provider. No network, dependency install or exec."""

import html
import json
from typing import Protocol

from app.agents.base import Agent
from app.development.models import Bundle, DevelopmentRequest, SourceFile
from app.portfolio.planning import PlanRecord
from app.tasks.models import Task


def selected_tasks(source: PlanRecord, request: DevelopmentRequest) -> tuple[str, ...]:
    if source.audit.id != request.plan_id:
        raise ValueError("Plan id differs from development request")
    if not source.review or source.review.outcome != "approved":
        raise ValueError("Human-approved source plan required")
    scope = source.audit.result.scope
    if source.audit.result.outcome != "ready_for_review" or scope is None:
        raise ValueError("Source plan cannot support development")
    tasks = {t.id: t for t in scope.tasks}
    requested = set(request.task_ids)
    if not requested <= tasks.keys():
        raise ValueError("Unknown planned task")
    if any(not set(tasks[key].dependencies) <= requested for key in requested):
        raise ValueError("Select all dependencies with the requested tasks")
    order = tuple(key for key in source.audit.result.task_order if key in requested)
    if set(order) != requested or len(order) != len(requested):
        raise ValueError("Source plan task order is inconsistent")
    return order


class DevelopmentProvider(Protocol):
    def generate(self, source: PlanRecord, request: DevelopmentRequest) -> Bundle: ...


class StaticPrototypeProvider:
    """Only a visual scaffold and acceptance checklist, never full task completion."""

    def generate(self, source: PlanRecord, request: DevelopmentRequest) -> Bundle:
        order = selected_tasks(source, request)
        scope = source.audit.result.scope
        assert scope is not None
        tasks = {t.id: t for t in scope.tasks}
        requirements = {rid for key in order for rid in tasks[key].requirement_ids}
        cards = "\n".join(
            "<section><h2>"
            + html.escape(tasks[key].deliverable)
            + "</h2><ul>"
            + "".join(
                "<li>" + html.escape(c) + "</li>"
                for c in tasks[key].acceptance_criteria
            )
            + "</ul><p>Pending implementation and human acceptance review.</p>"
            "</section>"
            for key in order
        )
        page = (
            '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            '<meta http-equiv="Content-Security-Policy" '
            "content=\"default-src 'none'; style-src 'unsafe-inline'; "
            "base-uri 'none'; form-action 'none'\">\n"
            "<title>JACK prototype</title><style>"
            "body{font-family:system-ui;margin:3rem auto;padding:0 1rem;"
            "max-width:64rem;background:#f5f7fa;color:#162335}"
            "section{background:white;padding:1.5rem;margin:1rem 0;border-radius:1rem}"
            "li{margin:.6rem 0}p{line-height:1.6}</style></head><body>\n"
            "<main><p>LOCAL PROTOTYPE · NOT A COMPLETED PRODUCT</p><h1>"
            + html.escape(scope.objective)
            + "</h1>\n"
            + cards
            + "\n<p>No records are saved. No payments or external services are "
            "connected. Review scope.json and REVIEW.md before further work.</p>"
            "</main></body></html>\n"
        )
        proposal = {
            "plan_id": str(source.audit.id),
            "objective": scope.objective,
            "requirements": [
                r.model_dump(mode="json")
                for r in scope.requirements
                if r.id in requirements
            ],
            "tasks": [tasks[key].model_dump(mode="json") for key in order],
            "risks": [r.model_dump(mode="json") for r in scope.risks],
            "exclusions": scope.exclusions,
            "assumptions": scope.assumptions,
            "limitations": [
                "Static visual scaffold only; requirements are not implemented.",
                "All acceptance checks remain pending human verification.",
                "No code executed, dependencies installed or deployment authorized.",
            ],
        }
        return Bundle(
            files=(
                SourceFile(path="index.html", content=page),
                SourceFile(
                    path="scope.json",
                    content=json.dumps(
                        proposal, ensure_ascii=True, sort_keys=True, indent=2
                    )
                    + "\n",
                ),
                SourceFile(
                    path="REVIEW.md",
                    content=(
                        "# Prototype review\n\n"
                        "Open index.html locally for a static visual scaffold.\n"
                        "No application behavior or storage is implemented.\n\n"
                        "Review every requirement and task in scope.json. "
                        "All acceptance "
                        "criteria are pending; no task is marked complete.\n"
                        "Check provenance and hashes in manifest.json.\n"
                        "Approval of a plan is not authorization to execute generated "
                        "code, install packages, spend funds or deploy.\n"
                    ),
                ),
            ),
            task_order=order,
        )


class DevelopmentAgent(Agent):
    """Explicit coordinator supplies a resolved, approved plan; returns JSON only."""

    def __init__(self, provider: DevelopmentProvider | None = None):
        self.provider = provider if provider is not None else StaticPrototypeProvider()

    def execute(self, task: Task) -> str:
        from app.development.service import DevelopmentContext

        if not task.result:
            raise ValueError("Development requires resolved DevelopmentContext JSON")
        context = DevelopmentContext.model_validate_json(task.result)
        return self.provider.generate(
            context.source_plan, context.request
        ).model_dump_json()
