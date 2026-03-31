from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from self_healing_agent.config import settings
from self_healing_agent.db import Base
from self_healing_agent.domain.models import (
    AuditEvent,
    ConfidenceScore,
    DashboardSummary,
    DashboardTrendPoint,
    DashboardTrends,
    RecurringIssueEntry,
    RecurringIssuesReport,
    FailureAnalysis,
    PatchCandidate,
    PullRequestInfo,
    RepairRun,
    RunArtifact,
    ValidationResult,
    WorkflowFailure,
)
from self_healing_agent.services.audit import normalize_audit_events


class RepairRunRecord(Base):
    __tablename__ = "repair_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    repository: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    workflow_run_id: Mapped[int] = mapped_column(nullable=False, index=True)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sha: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    branch: Mapped[str] = mapped_column(String(255), nullable=False)
    failed_job: Mapped[str] = mapped_column(String(255), nullable=False)
    failed_step: Mapped[str] = mapped_column(String(255), nullable=False)
    log_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    html_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    analysis_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    patch_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    validation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    confidence_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    pull_request_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )

    audit_events: Mapped[list["AuditEventRecord"]] = relationship(
        back_populates="repair_run", cascade="all, delete-orphan"
    )


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("repair_runs.run_id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    repair_run: Mapped[RepairRunRecord] = relationship(back_populates="audit_events")


class ArtifactRecord(Base):
    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("repair_runs.run_id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class SqlAlchemyRepairRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert(self, run: RepairRun) -> RepairRun:
        record = self.session.get(RepairRunRecord, run.run_id)
        if record is None:
            record = RepairRunRecord(run_id=run.run_id)
            self.session.add(record)

        failure = run.failure
        record.status = run.status.value
        record.category = run.category.value
        record.decision = run.decision.value
        record.repository = failure.repository
        record.workflow_run_id = failure.workflow_run_id
        record.workflow_name = failure.workflow_name
        record.sha = failure.sha
        record.branch = failure.branch
        record.failed_job = failure.failed_job
        record.failed_step = failure.failed_step
        record.log_excerpt = failure.log_excerpt
        record.html_url = failure.html_url
        record.context_json = failure.context
        record.analysis_json = run.analysis.model_dump() if run.analysis else None
        record.patch_json = run.patch.model_dump() if run.patch else None
        record.validation_json = run.validation.model_dump() if run.validation else None
        record.confidence_json = run.confidence.model_dump() if run.confidence else None
        record.pull_request_json = run.pull_request.model_dump() if run.pull_request else None
        record.metadata_json = run.metadata

        self.session.execute(delete(AuditEventRecord).where(AuditEventRecord.run_id == run.run_id))
        for sequence, event in enumerate(
            normalize_audit_events(run.metadata.get("audit_events", [])), start=1
        ):
            self.session.add(
                AuditEventRecord(
                    run_id=run.run_id,
                    sequence=sequence,
                    event_type=event.event,
                    payload_json=event.payload,
                )
            )

        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def get(self, run_id: str) -> RepairRun | None:
        record = self.session.get(RepairRunRecord, run_id)
        if record is None:
            return None
        return self._to_domain(record)

    def list_runs(
        self,
        *,
        repository: str | None = None,
        status: str | None = None,
        category: str | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[RepairRun]:
        query = select(RepairRunRecord).order_by(RepairRunRecord.created_at.desc())

        if repository:
            query = query.where(RepairRunRecord.repository == repository)
        if status:
            query = query.where(RepairRunRecord.status == status)
        if category:
            query = query.where(RepairRunRecord.category == category)
        if search:
            like = f"%{search}%"
            query = query.where(
                RepairRunRecord.repository.ilike(like)
                | RepairRunRecord.workflow_name.ilike(like)
                | RepairRunRecord.failed_job.ilike(like)
                | RepairRunRecord.failed_step.ilike(like)
                | RepairRunRecord.log_excerpt.ilike(like)
            )
        if limit is not None:
            query = query.limit(limit)

        records = self.session.scalars(query).all()
        return [self._to_domain(record) for record in records]

    def dashboard_summary(self) -> DashboardSummary:
        runs = self.list_runs()
        categories = Counter(run.category.value for run in runs)
        validated = [run for run in runs if run.validation and run.validation.passed]
        pr_created = [run for run in runs if run.status.value == "pr_created"]
        false_positives = [run for run in runs if run.metadata.get("false_positive", False)]
        recurring = Counter(
            (run.analysis.summary if run.analysis else run.failure.failed_step)
            for run in runs
        )
        return DashboardSummary(
            failures_detected=len(runs),
            categories=dict(categories),
            fix_success_rate=(len(validated) / len(runs)) if runs else 0.0,
            false_positive_rate=(len(false_positives) / len(pr_created)) if pr_created else 0.0,
            time_saved_hours=round(
                sum(float(run.metadata.get("time_saved_hours", 0.0)) for run in runs), 2
            ),
            top_recurring_issues=[issue for issue, _ in recurring.most_common(5)],
        )

    def dashboard_trends(self, days: int = 7) -> DashboardTrends:
        clamped_days = max(1, min(days, 30))
        today = date.today()
        start_date = today - timedelta(days=clamped_days - 1)
        records = self.session.scalars(
            select(RepairRunRecord)
            .where(RepairRunRecord.created_at >= datetime.combine(start_date, datetime.min.time()))
            .order_by(RepairRunRecord.created_at.asc())
        ).all()

        buckets: dict[str, list[RepairRunRecord]] = {(
            today - timedelta(days=offset)
        ).isoformat(): [] for offset in range(clamped_days - 1, -1, -1)}

        for record in records:
            bucket = record.created_at.date().isoformat()
            if bucket in buckets:
                buckets[bucket].append(record)

        points: list[DashboardTrendPoint] = []
        for bucket_date in buckets:
            bucket_records = buckets[bucket_date]
            points.append(
                DashboardTrendPoint(
                    date=bucket_date,
                    failures_detected=len(bucket_records),
                    validated_fixes=sum(
                        1
                        for record in bucket_records
                        if record.validation_json and record.validation_json.get("passed")
                    ),
                    pull_requests_created=sum(
                        1
                        for record in bucket_records
                        if record.pull_request_json
                        and record.pull_request_json.get("status") == "created"
                    ),
                    time_saved_hours=round(
                        sum(float((record.metadata_json or {}).get("time_saved_hours", 0.0)) for record in bucket_records),
                        2,
                    ),
                )
            )

        return DashboardTrends(
            days=clamped_days,
            points=points,
            failures_detected=sum(point.failures_detected for point in points),
            validated_fixes=sum(point.validated_fixes for point in points),
            pull_requests_created=sum(point.pull_requests_created for point in points),
            time_saved_hours=round(sum(point.time_saved_hours for point in points), 2),
        )

    def recurring_issues(self, days: int = 30, limit: int = 20) -> RecurringIssuesReport:
        clamped_days = max(1, min(days, 90))
        start_date = date.today() - timedelta(days=clamped_days - 1)
        records = self.session.scalars(
            select(RepairRunRecord)
            .where(RepairRunRecord.created_at >= datetime.combine(start_date, datetime.min.time()))
            .order_by(RepairRunRecord.created_at.desc())
        ).all()

        buckets: dict[str, dict[str, Any]] = {}
        for record in records:
            analysis = record.analysis_json or {}
            fingerprint = str(analysis.get("fingerprint") or (record.metadata_json or {}).get("failure_fingerprint") or "")
            if not fingerprint:
                continue

            category = record.category
            bucket = buckets.setdefault(
                fingerprint,
                {
                    "summary": str(analysis.get("summary") or record.failed_step),
                    "category": category,
                    "occurrences": 0,
                    "repositories": set(),
                    "workflows": set(),
                    "last_seen": None,
                    "known_fixer_available": category in {"lint", "dependency", "import", "workflow"},
                },
            )
            bucket["occurrences"] += 1
            bucket["repositories"].add(record.repository)
            bucket["workflows"].add(record.workflow_name)
            last_seen = record.created_at.isoformat() if record.created_at else None
            if last_seen and (bucket["last_seen"] is None or last_seen > bucket["last_seen"]):
                bucket["last_seen"] = last_seen

        issues = sorted(
            [
                RecurringIssueEntry(
                    fingerprint=fingerprint,
                    summary=data["summary"],
                    category=data["category"],
                    occurrences=data["occurrences"],
                    repositories=sorted(data["repositories"]),
                    workflows=sorted(data["workflows"]),
                    last_seen=data["last_seen"],
                    known_fixer_available=bool(data["known_fixer_available"]),
                )
                for fingerprint, data in buckets.items()
            ],
            key=lambda issue: (-issue.occurrences, issue.summary),
        )[:limit]

        return RecurringIssuesReport(days=clamped_days, issues=issues)

    def save_artifact(
        self,
        run_id: str,
        kind: str,
        name: str,
        content: str,
        content_type: str = "text/plain",
    ) -> RunArtifact:
        artifact_id = str(uuid4())
        artifact_path = artifact_file_path(run_id, artifact_id, name)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(content, encoding="utf-8")
        preview = content[:400]
        record = ArtifactRecord(
            artifact_id=artifact_id,
            run_id=run_id,
            kind=kind,
            name=name,
            content_type=content_type,
            path=str(artifact_path),
            size_bytes=len(content.encode("utf-8")),
            preview=preview,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_artifact(record)

    def list_artifacts(self, run_id: str) -> list[RunArtifact]:
        records = self.session.scalars(
            select(ArtifactRecord)
            .where(ArtifactRecord.run_id == run_id)
            .order_by(ArtifactRecord.created_at.asc())
        ).all()
        return [self._to_artifact(record) for record in records]

    def get_artifact(self, run_id: str, artifact_id: str) -> RunArtifact | None:
        record = self.session.scalar(
            select(ArtifactRecord).where(
                ArtifactRecord.run_id == run_id,
                ArtifactRecord.artifact_id == artifact_id,
            )
        )
        if record is None:
            return None
        return self._to_artifact(record)

    def read_artifact(self, run_id: str, artifact_id: str) -> str | None:
        record = self.session.scalar(
            select(ArtifactRecord).where(
                ArtifactRecord.run_id == run_id,
                ArtifactRecord.artifact_id == artifact_id,
            )
        )
        if record is None:
            return None

        path = Path(record.path)
        try:
            resolved = path.resolve()
            artifact_root = Path(settings.artifact_storage_path).resolve()
        except OSError:
            return None

        if artifact_root not in resolved.parents and resolved != artifact_root:
            return None
        if not resolved.exists() or not resolved.is_file():
            return None

        try:
            return resolved.read_text(encoding="utf-8")
        except OSError:
            return None

    def _to_domain(self, record: RepairRunRecord) -> RepairRun:
        metadata = dict(record.metadata_json or {})
        events = self.session.scalars(
            select(AuditEventRecord)
            .where(AuditEventRecord.run_id == record.run_id)
            .order_by(AuditEventRecord.sequence.asc())
        ).all()
        metadata["audit_events"] = [
            AuditEvent(event=event.event_type, payload=event.payload_json or {}).model_dump()
            for event in events
        ]

        return RepairRun(
            run_id=record.run_id,
            status=record.status,
            analysis=FailureAnalysis.model_validate(record.analysis_json)
            if record.analysis_json
            else None,
            category=record.category,
            decision=record.decision,
            failure=WorkflowFailure(
                repository=record.repository,
                workflow_run_id=record.workflow_run_id,
                workflow_name=record.workflow_name,
                sha=record.sha,
                branch=record.branch,
                failed_job=record.failed_job,
                failed_step=record.failed_step,
                log_excerpt=record.log_excerpt,
                html_url=record.html_url,
                context=record.context_json or {},
            ),
            patch=PatchCandidate.model_validate(record.patch_json) if record.patch_json else None,
            validation=ValidationResult.model_validate(record.validation_json)
            if record.validation_json
            else None,
            confidence=ConfidenceScore.model_validate(record.confidence_json)
            if record.confidence_json
            else None,
            pull_request=PullRequestInfo.model_validate(record.pull_request_json)
            if record.pull_request_json
            else None,
            metadata=metadata,
            created_at=record.created_at.isoformat() if record.created_at else None,
        )

    def _to_artifact(self, record: ArtifactRecord) -> RunArtifact:
        return RunArtifact(
            artifact_id=record.artifact_id,
            run_id=record.run_id,
            kind=record.kind,
            name=record.name,
            content_type=record.content_type,
            path=record.path,
            size_bytes=record.size_bytes,
            preview=record.preview,
        )


def artifact_file_path(run_id: str, artifact_id: str, name: str) -> Path:
    safe_name = name.replace("/", "_")
    return Path(settings.artifact_storage_path) / run_id / f"{artifact_id}_{safe_name}"
