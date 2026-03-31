from __future__ import annotations

import time

from self_healing_agent.config import settings
from self_healing_agent.db import SessionLocal
from self_healing_agent.repositories.jobs import SqlAlchemyRepairJobRepository
from self_healing_agent.repositories.sql import SqlAlchemyRepairRunRepository
from self_healing_agent.services.audit import add_audit_event
from self_healing_agent.workflows.engine import RepairWorkflowEngine


def run_worker_loop(poll_interval_seconds: float = 2.0) -> None:
    while True:
        processed = process_one_job()
        if not processed:
            time.sleep(poll_interval_seconds)


def process_one_job() -> bool:
    with SessionLocal() as session:
        job_repository = SqlAlchemyRepairJobRepository(session)
        job = job_repository.claim_next()
        if job is None:
            return False

        run_repository = SqlAlchemyRepairRunRepository(session)
        run = run_repository.get(job.run_id)
        if run is None:
            finalize_failed_job(
                job_repository,
                run_repository,
                job.job_id,
                job.run_id,
                job.attempts,
                job.max_attempts,
                f"Repair run not found for {job.run_id}",
            )
            return True

        try:
            engine = RepairWorkflowEngine(run_repository)
            engine.execute(run.failure, run_id=run.run_id)
            job_repository.mark_completed(job.job_id)
        except Exception as error:
            finalize_failed_job(
                job_repository,
                run_repository,
                job.job_id,
                job.run_id,
                job.attempts,
                job.max_attempts,
                str(error),
            )
        return True


def finalize_failed_job(
    repository: SqlAlchemyRepairJobRepository,
    run_repository: SqlAlchemyRepairRunRepository,
    job_id: str,
    run_id: str,
    attempts: int,
    max_attempts: int,
    error: str,
) -> None:
    run = run_repository.get(run_id)
    if attempts >= max_attempts:
        if run is not None:
            add_audit_event(
                run,
                "job_dead_lettered",
                {"job_id": job_id, "attempts": attempts, "error": error},
            )
            run_repository.upsert(run)
        repository.mark_dead_letter(job_id, error)
        return
    if run is not None:
        add_audit_event(
            run,
            "job_requeued",
            {"job_id": job_id, "attempts": attempts, "max_attempts": max_attempts, "error": error},
        )
        run_repository.upsert(run)
    repository.requeue(job_id, error)


def worker_health() -> dict[str, float | int]:
    return {
        "poll_interval_seconds": settings.worker_poll_interval_seconds,
        "max_attempts": settings.worker_max_attempts,
    }
