from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from self_healing_agent.config import settings
from self_healing_agent.db import get_session
from self_healing_agent.domain.models import (
    DashboardOverview,
    RecurringIssuesReport,
    AuditEvent,
    DashboardTrends,
    FailureAnalysis,
    JobCounts,
    JobTimelineEntry,
    RepairJob,
    RepairRun,
    RunArtifact,
    RunTimelineEntry,
    WorkflowFailure,
)
from self_healing_agent.repositories.jobs import SqlAlchemyRepairJobRepository
from self_healing_agent.repositories.sql import SqlAlchemyRepairRunRepository
from self_healing_agent.services.github import (
    enrich_workflow_run_context,
    github_integration_status,
    normalize_workflow_run_failure,
    probe_github_repository,
    verify_github_webhook_signature,
)
from self_healing_agent.services.ingest import create_detected_run
from self_healing_agent.services.queue import enqueue_repair_run
from self_healing_agent.worker import worker_health


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.run_db_migrations_on_startup:
        run_migrations()
    yield


app = FastAPI(
    title="Self-Healing CI/CD Agent API",
    version="0.1.0",
    description="Backend control plane for workflow ingestion, repair orchestration, and observability.",
    lifespan=lifespan,
)


def get_repository(session: Session = Depends(get_session)) -> SqlAlchemyRepairRunRepository:
    return SqlAlchemyRepairRunRepository(session)


def get_job_repository(session: Session = Depends(get_session)) -> SqlAlchemyRepairJobRepository:
    return SqlAlchemyRepairJobRepository(session)


def run_migrations() -> None:
    alembic_cfg = Config("apps/api/alembic.ini")
    command.upgrade(alembic_cfg, "head")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/integrations/github/status")
def get_github_status() -> dict:
    return github_integration_status()


@app.get("/api/integrations/github/repositories/{owner}/{repo}/probe")
def probe_github_repo(owner: str, repo: str) -> dict:
    return probe_github_repository(f"{owner}/{repo}")


@app.get("/api/worker/health")
def get_worker_health(
    repository: SqlAlchemyRepairJobRepository = Depends(get_job_repository),
) -> dict:
    jobs = repository.list_jobs()
    return {
        "status": "ok",
        **worker_health(),
        "queued_jobs": sum(1 for job in jobs if job.status == "queued"),
        "running_jobs": sum(1 for job in jobs if job.status == "running"),
        "failed_jobs": sum(1 for job in jobs if job.status == "failed"),
        "dead_letter_jobs": sum(1 for job in jobs if job.status == "dead_letter"),
    }


@app.get("/api/dashboard/summary")
def dashboard_summary(
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
) -> dict:
    return repository.dashboard_summary().model_dump()


@app.get("/api/dashboard/overview", response_model=DashboardOverview)
def dashboard_overview(
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
    job_repository: SqlAlchemyRepairJobRepository = Depends(get_job_repository),
) -> DashboardOverview:
    runs = repository.list_runs(limit=8)
    jobs = job_repository.list_jobs(limit=8)
    return DashboardOverview(
        summary=repository.dashboard_summary(),
        job_counts=JobCounts(
            queued=sum(1 for job in jobs if job.status == "queued"),
            running=sum(1 for job in jobs if job.status == "running"),
            completed=sum(1 for job in jobs if job.status == "completed"),
            failed=sum(
                1 for job in jobs if job.status in {"failed", "dead_letter"}
            ),
        ),
        recent_runs=runs[:8],
        recent_jobs=jobs[:8],
    )


@app.get("/api/dashboard/trends", response_model=DashboardTrends)
def dashboard_trends(
    days: int = 7,
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
) -> DashboardTrends:
    return repository.dashboard_trends(days=days)


@app.get("/api/dashboard/recurring-issues", response_model=RecurringIssuesReport)
def recurring_issues(
    days: int = 30,
    limit: int = 20,
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
) -> RecurringIssuesReport:
    return repository.recurring_issues(days=days, limit=limit)


@app.get("/api/runs", response_model=list[RepairRun])
def list_runs(
    repository_name: str | None = None,
    status: str | None = None,
    category: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
) -> list[RepairRun]:
    return repository.list_runs(
        repository=repository_name,
        status=status,
        category=category,
        search=search,
        limit=limit,
    )


@app.get("/api/runs/{run_id}", response_model=RepairRun)
def get_run(
    run_id: str,
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
) -> RepairRun:
    run = repository.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/api/runs/{run_id}/analysis", response_model=FailureAnalysis)
def get_run_analysis(
    run_id: str,
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
) -> FailureAnalysis:
    run = repository.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run.analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return run.analysis


@app.get("/api/runs/{run_id}/timeline", response_model=list[RunTimelineEntry])
def get_run_timeline(
    run_id: str,
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
) -> list[RunTimelineEntry]:
    run = repository.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return [
        RunTimelineEntry(
            sequence=index,
            event=event.event,
            payload=event.payload,
        )
        for index, event in enumerate(
            [
                AuditEvent.model_validate(item)
                if isinstance(item, dict)
                else AuditEvent(event=str(item), payload={})
                for item in run.metadata.get("audit_events", [])
            ],
            start=1,
        )
    ]


@app.get("/api/runs/{run_id}/artifacts", response_model=list[RunArtifact])
def get_run_artifacts(
    run_id: str,
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
) -> list[RunArtifact]:
    run = repository.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return repository.list_artifacts(run_id)


@app.get("/api/runs/{run_id}/artifacts/{artifact_id}", response_model=RunArtifact)
def get_run_artifact(
    run_id: str,
    artifact_id: str,
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
) -> RunArtifact:
    run = repository.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    artifact = repository.get_artifact(run_id, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return artifact


@app.get(
    "/api/runs/{run_id}/artifacts/{artifact_id}/content",
    response_class=PlainTextResponse,
)
def get_run_artifact_content(
    run_id: str,
    artifact_id: str,
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
) -> PlainTextResponse:
    run = repository.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    artifact = repository.get_artifact(run_id, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    content = repository.read_artifact(run_id, artifact_id)
    if content is None:
        raise HTTPException(status_code=404, detail="Artifact content not available")
    return PlainTextResponse(content=content, media_type=artifact.content_type)


@app.get("/api/jobs", response_model=list[RepairJob])
def list_jobs(
    status: str | None = None,
    run_id: str | None = None,
    search: str | None = None,
    limit: int | None = None,
    repository: SqlAlchemyRepairJobRepository = Depends(get_job_repository),
) -> list[RepairJob]:
    return repository.list_jobs(
        status=status,
        run_id=run_id,
        search=search,
        limit=limit,
    )


@app.get("/api/jobs/{job_id}", response_model=RepairJob)
def get_job(
    job_id: str,
    repository: SqlAlchemyRepairJobRepository = Depends(get_job_repository),
) -> RepairJob:
    job = repository.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/jobs/{job_id}/timeline", response_model=list[JobTimelineEntry])
def get_job_timeline(
    job_id: str,
    repository: SqlAlchemyRepairJobRepository = Depends(get_job_repository),
) -> list[JobTimelineEntry]:
    job = repository.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    history = job.payload.get("history", [])
    return [
        JobTimelineEntry(
            sequence=index,
            status=str(item.get("status", "unknown")),
            error=item.get("error"),
            attempts=int(item.get("attempts", 0)),
            timestamp=item.get("timestamp"),
            details=item.get("details") or {},
        )
        for index, item in enumerate(history, start=1)
        if isinstance(item, dict)
    ]


@app.post("/api/failures", response_model=RepairRun)
def ingest_failure(
    payload: WorkflowFailure,
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
    job_repository: SqlAlchemyRepairJobRepository = Depends(get_job_repository),
) -> RepairRun:
    run = create_detected_run(payload)
    repository.upsert(run)
    job = enqueue_repair_run(job_repository, run)
    run.metadata["job_id"] = job.job_id
    return repository.upsert(run)


@app.post("/api/webhooks/github")
async def ingest_github_webhook(
    request: Request,
    repository: SqlAlchemyRepairRunRepository = Depends(get_repository),
    job_repository: SqlAlchemyRepairJobRepository = Depends(get_job_repository),
) -> dict:
    body = await request.body()
    verify_github_webhook_signature(request.headers.get("x-hub-signature-256"), body)

    event_name = request.headers.get("x-github-event", "")
    delivery_id = request.headers.get("x-github-delivery", "")
    payload = await request.json()

    if event_name != "workflow_run":
        return {
            "status": "ignored",
            "reason": f"unsupported_event:{event_name or 'unknown'}",
            "delivery_id": delivery_id,
        }

    payload["_shca_context"] = await enrich_workflow_run_context(payload)
    failure = normalize_workflow_run_failure(payload)
    if failure is None:
        return {
            "status": "ignored",
            "reason": "workflow_run_not_failed",
            "delivery_id": delivery_id,
        }

    run = create_detected_run(failure)
    repository.upsert(run)
    job = enqueue_repair_run(job_repository, run)
    run.metadata["job_id"] = job.job_id
    repository.upsert(run)
    return {
        "status": "queued",
        "delivery_id": delivery_id,
        "run_id": run.run_id,
        "job_id": job.job_id,
        "repository": run.failure.repository,
        "workflow_run_id": run.failure.workflow_run_id,
        "context_available": run.failure.context.get("available", False),
    }
