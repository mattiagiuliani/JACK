"""Immutable artifacts from persisted approved plans, with a local export receipt."""

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import AwareDatetime
from sqlalchemy import String, Text, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.agents.development import StaticPrototypeProvider, selected_tasks
from app.agents.research import ResearchModel
from app.db.base import Base
from app.development.models import Bundle, DevelopmentRequest, ExportRequest
from app.development.workspace import materialize
from app.portfolio.planning import PlanningService, PlanRecord
from app.portfolio.service import PortfolioConflict, PortfolioService


class ArtifactDB(Base):
    __tablename__ = "development_artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    report: Mapped[str] = mapped_column(Text, nullable=False)
    export: Mapped[str | None] = mapped_column(Text, nullable=True)


class DevelopmentContext(ResearchModel):
    request: DevelopmentRequest
    source_plan: PlanRecord


class DevelopmentReport(DevelopmentContext):
    id: UUID
    created_at: AwareDatetime
    bundle: Bundle
    bundle_sha256: str


class ExportRecord(ExportRequest):
    recorded_at: AwareDatetime
    workspace: str
    bundle_sha256: str


class ArtifactRecord(ResearchModel):
    report: DevelopmentReport
    export: ExportRecord | None = None


class DevelopmentService:
    def __init__(self, session: Session):
        self.session = session

    def get(self, artifact_id: UUID) -> ArtifactRecord:
        row = self.session.get(ArtifactDB, str(artifact_id), populate_existing=True)
        if row is None:
            raise LookupError("Development artifact not found")
        report = DevelopmentReport.model_validate_json(row.report)
        if report.bundle.fingerprint() != report.bundle_sha256:
            raise PortfolioConflict("Stored artifact integrity check failed")
        return ArtifactRecord(
            report=report,
            export=ExportRecord.model_validate_json(row.export) if row.export else None,
        )

    def fresh_plan(self, request: DevelopmentRequest) -> PlanRecord:
        source = PlanningService(self.session).get(request.plan_id)
        if not source.review or source.review.outcome != "approved":
            raise PortfolioConflict("Human-approved source plan required")
        selected_tasks(source, request)
        venture = source.audit.context.venture
        snapshots = (
            source.audit.decision.report.snapshots
            if source.audit.decision
            else (venture,)
        )
        if any(
            PortfolioService(self.session).get(v.id).version != v.version
            for v in snapshots
        ):
            raise PortfolioConflict("Portfolio changed; obtain a fresh approved plan")
        return source

    def create(self, key: str, request: DevelopmentRequest) -> ArtifactRecord:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", key):
            raise ValueError("Invalid idempotency key")
        try:
            row = self.session.scalar(select(ArtifactDB).where(ArtifactDB.key == key))
            if row is not None:
                if row.request != request.model_dump_json():
                    raise PortfolioConflict("Idempotency key reused")
                return self.get(UUID(row.id))
            source = self.fresh_plan(request)
            bundle = StaticPrototypeProvider().generate(source, request)
            report = DevelopmentReport(
                id=uuid4(),
                created_at=datetime.now(UTC),
                request=request,
                source_plan=source,
                bundle=bundle,
                bundle_sha256=bundle.fingerprint(),
            )
            self.session.add(
                ArtifactDB(
                    id=str(report.id),
                    key=key,
                    request=request.model_dump_json(),
                    report=report.model_dump_json(),
                )
            )
            self.session.commit()
            return self.get(report.id)
        except (IntegrityError, OperationalError) as exc:
            self.session.rollback()
            raise PortfolioConflict(
                "Concurrent development write; retry same key"
            ) from exc
        except Exception:
            self.session.rollback()
            raise

    def export(
        self, artifact_id: UUID, request: ExportRequest, root: Path
    ) -> ArtifactRecord:
        try:
            record = self.get(artifact_id)
            if record.export:
                previous = ExportRequest.model_validate(
                    record.export.model_dump(include={"actor", "reason"})
                )
                if previous != request:
                    raise PortfolioConflict(
                        "Artifact already exported by another request"
                    )
                if Path(record.export.workspace).parent != root.absolute():
                    raise PortfolioConflict("Configured workspace root changed")
            # Check freshness even on retries; historical GET remains available.
            self.fresh_plan(record.report.request)
            path = materialize(root, artifact_id, record.report.bundle)
            if record.export:
                return record
            receipt = ExportRecord(
                **request.model_dump(),
                recorded_at=datetime.now(UTC),
                workspace=str(path),
                bundle_sha256=record.report.bundle_sha256,
            )
            result = self.session.execute(
                update(ArtifactDB)
                .where(ArtifactDB.id == str(artifact_id), ArtifactDB.export.is_(None))
                .values(export=receipt.model_dump_json())
            )
            assert isinstance(result, CursorResult)
            if result.rowcount != 1:
                raise PortfolioConflict("Concurrent export receipt; reload artifact")
            self.session.commit()
            return self.get(artifact_id)
        except (IntegrityError, OperationalError) as exc:
            self.session.rollback()
            raise PortfolioConflict("Concurrent export; retry same request") from exc
        except Exception:
            self.session.rollback()
            raise
