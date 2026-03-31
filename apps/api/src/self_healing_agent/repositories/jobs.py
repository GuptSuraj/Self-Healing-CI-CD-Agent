from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Text, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from self_healing_agent.db import Base
from self_healing_agent.domain.models import JobStatus, RepairJob


class RepairJobRecord(Base):
    __tablename__ = "repair_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(nullable=False, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class SqlAlchemyRepairJobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _append_history(
        self,
        record: RepairJobRecord,
        *,
        status: str,
        error: str | None = None,
        details: dict | None = None,
    ) -> None:
        payload = dict(record.payload_json or {})
        history = list(payload.get("history", []))
        history.append(
            {
                "status": status,
                "error": error,
                "attempts": record.attempts,
                "timestamp": datetime.utcnow().isoformat(),
                "details": details or {},
            }
        )
        payload["history"] = history
        record.payload_json = payload

    def enqueue(self, job: RepairJob) -> RepairJob:
        record = RepairJobRecord(
            job_id=job.job_id,
            run_id=job.run_id,
            status=job.status.value,
            payload_json=job.payload,
            error_text=job.error,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
        )
        self._append_history(
            record,
            status=record.status,
            details={"event": "enqueued", "max_attempts": record.max_attempts},
        )
        self.session.add(record)
        self.session.commit()
        return self.get(job.job_id) or job

    def get(self, job_id: str) -> RepairJob | None:
        record = self.session.get(RepairJobRecord, job_id)
        if record is None:
            return None
        return self._to_domain(record)

    def list_jobs(
        self,
        *,
        status: str | None = None,
        run_id: str | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[RepairJob]:
        query = select(RepairJobRecord).order_by(RepairJobRecord.created_at.desc())

        if status:
            query = query.where(RepairJobRecord.status == status)
        if run_id:
            query = query.where(RepairJobRecord.run_id == run_id)
        if search:
            like = f"%{search}%"
            query = query.where(
                RepairJobRecord.job_id.ilike(like)
                | RepairJobRecord.run_id.ilike(like)
                | RepairJobRecord.error_text.ilike(like)
            )
        if limit is not None:
            query = query.limit(limit)

        records = self.session.scalars(query).all()
        return [self._to_domain(record) for record in records]

    def claim_next(self) -> RepairJob | None:
        record = self.session.scalars(
            select(RepairJobRecord)
            .where(RepairJobRecord.status == JobStatus.QUEUED.value)
            .order_by(RepairJobRecord.created_at.asc())
        ).first()
        if record is None:
            return None
        record.status = JobStatus.RUNNING.value
        record.error_text = None
        record.attempts = record.attempts + 1
        self._append_history(
            record,
            status=record.status,
            details={"event": "claimed"},
        )
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def mark_completed(self, job_id: str) -> RepairJob | None:
        record = self.session.get(RepairJobRecord, job_id)
        if record is None:
            return None
        record.status = JobStatus.COMPLETED.value
        record.error_text = None
        self._append_history(
            record,
            status=record.status,
            details={"event": "completed"},
        )
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def mark_failed(self, job_id: str, error: str) -> RepairJob | None:
        record = self.session.get(RepairJobRecord, job_id)
        if record is None:
            return None
        record.status = JobStatus.FAILED.value
        record.error_text = error
        self._append_history(
            record,
            status=record.status,
            error=error,
            details={"event": "failed"},
        )
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def requeue(self, job_id: str, error: str) -> RepairJob | None:
        record = self.session.get(RepairJobRecord, job_id)
        if record is None:
            return None
        record.status = JobStatus.QUEUED.value
        record.error_text = error
        self._append_history(
            record,
            status=record.status,
            error=error,
            details={"event": "requeued"},
        )
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def mark_dead_letter(self, job_id: str, error: str) -> RepairJob | None:
        record = self.session.get(RepairJobRecord, job_id)
        if record is None:
            return None
        record.status = JobStatus.DEAD_LETTER.value
        record.error_text = error
        self._append_history(
            record,
            status=record.status,
            error=error,
            details={"event": "dead_lettered"},
        )
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def delete_for_run(self, run_id: str) -> None:
        self.session.execute(delete(RepairJobRecord).where(RepairJobRecord.run_id == run_id))
        self.session.commit()

    def _to_domain(self, record: RepairJobRecord) -> RepairJob:
        return RepairJob(
            job_id=record.job_id,
            run_id=record.run_id,
            status=record.status,
            payload=record.payload_json or {},
            error=record.error_text,
            attempts=record.attempts,
            max_attempts=record.max_attempts,
            created_at=record.created_at.isoformat() if record.created_at else None,
        )
