from __future__ import annotations

from uuid import uuid4

from self_healing_agent.config import settings
from self_healing_agent.domain.models import JobStatus, RepairJob, RepairRun
from self_healing_agent.repositories.jobs import SqlAlchemyRepairJobRepository


def enqueue_repair_run(
    repository: SqlAlchemyRepairJobRepository,
    run: RepairRun,
) -> RepairJob:
    payload = {
        "run_id": run.run_id,
        "repository": run.failure.repository,
        "workflow_run_id": run.failure.workflow_run_id,
    }
    job = RepairJob(
        job_id=str(uuid4()),
        run_id=run.run_id,
        status=JobStatus.QUEUED,
        payload=payload,
        attempts=0,
        max_attempts=settings.worker_max_attempts,
    )
    return repository.enqueue(job)
