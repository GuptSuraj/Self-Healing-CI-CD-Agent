from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from self_healing_agent.api.main import app, get_job_repository, get_repository
from self_healing_agent.domain.models import (
    AuditEvent,
    FailureAnalysis,
    FailureCategory,
    JobStatus,
    PullRequestInfo,
    RepairDecision,
    RepairJob,
    RepairRun,
    RunStatus,
    ValidationResult,
    WorkflowFailure,
)
from self_healing_agent.repositories.memory import InMemoryRepairRunRepository


class FakeJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, RepairJob] = {}

    def enqueue(self, job: RepairJob) -> RepairJob:
        history = [
            {
                "status": job.status.value,
                "error": None,
                "attempts": job.attempts,
                "timestamp": "2026-03-31T10:00:00",
                "details": {"event": "enqueued"},
            }
        ]
        job.payload = {**job.payload, "history": history}
        self.jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> RepairJob | None:
        return self.jobs.get(job_id)

    def list_jobs(
        self,
        *,
        status: str | None = None,
        run_id: str | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[RepairJob]:
        jobs = list(self.jobs.values())
        if status:
            jobs = [job for job in jobs if job.status.value == status]
        if run_id:
            jobs = [job for job in jobs if job.run_id == run_id]
        if search:
            needle = search.lower()
            jobs = [
                job
                for job in jobs
                if needle in job.job_id.lower()
                or needle in job.run_id.lower()
                or needle in (job.error or "").lower()
            ]
        return jobs[:limit] if limit is not None else jobs


def build_failure() -> WorkflowFailure:
    return WorkflowFailure(
        repository="acme/example",
        workflow_run_id=55,
        workflow_name="ci",
        sha="abc1234",
        branch="main",
        failed_job="tests",
        failed_step="failing step",
        log_excerpt="traceback here",
    )


def build_run() -> RepairRun:
    failure = build_failure()
    return RepairRun(
        run_id="run-123",
        status=RunStatus.PR_CREATED,
        failure=failure,
        analysis=FailureAnalysis(
            fingerprint="fp-api",
            summary="lint failure in tests",
            category_signals=["lint"],
            likely_root_cause="Trailing whitespace caused lint failure.",
            evidence=["failed_step=failing step"],
            bounded_context={},
        ),
        category=FailureCategory.LINT,
        decision=RepairDecision.REPAIR,
        validation=ValidationResult(
            status="passed",
            passed=True,
            reproducible=True,
            failure_observed=True,
            flaky=False,
            executed_commands=["ruff check app.py"],
            logs="ok",
        ),
        pull_request=PullRequestInfo(status="created", url="https://example/pr/1"),
        metadata={
            "time_saved_hours": 0.5,
            "audit_events": [
                AuditEvent(event="analysis_completed", payload={"fingerprint": "fp-api"}).model_dump(),
                AuditEvent(event="draft_pr_created", payload={"number": 1}).model_dump(),
            ],
        },
        created_at="2026-03-31T10:00:00",
    )


class ApiEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run_repository = InMemoryRepairRunRepository()
        self.job_repository = FakeJobRepository()

        existing_run = build_run()
        self.run_repository.upsert(existing_run)
        self.run_repository.save_artifact(
            existing_run.run_id,
            kind="validation_log",
            name="validation.log",
            content="validation output",
        )
        self.job_repository.enqueue(
            RepairJob(
                job_id="job-123",
                run_id=existing_run.run_id,
                status=JobStatus.QUEUED,
                payload={"run_id": existing_run.run_id},
                attempts=0,
                max_attempts=3,
            )
        )

        app.dependency_overrides[get_repository] = lambda: self.run_repository
        app.dependency_overrides[get_job_repository] = lambda: self.job_repository
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_dashboard_and_run_detail_endpoints(self) -> None:
        overview = self.client.get("/api/dashboard/overview")
        self.assertEqual(200, overview.status_code)
        self.assertEqual(1, overview.json()["summary"]["failures_detected"])

        run = self.client.get("/api/runs/run-123")
        self.assertEqual(200, run.status_code)
        self.assertEqual("run-123", run.json()["run_id"])

        timeline = self.client.get("/api/runs/run-123/timeline")
        self.assertEqual(200, timeline.status_code)
        self.assertEqual("analysis_completed", timeline.json()[0]["event"])

        artifacts = self.client.get("/api/runs/run-123/artifacts")
        self.assertEqual(200, artifacts.status_code)
        self.assertEqual("validation_log", artifacts.json()[0]["kind"])

    def test_job_endpoints_return_timeline(self) -> None:
        response = self.client.get("/api/jobs/job-123")
        self.assertEqual(200, response.status_code)
        self.assertEqual("job-123", response.json()["job_id"])

        timeline = self.client.get("/api/jobs/job-123/timeline")
        self.assertEqual(200, timeline.status_code)
        self.assertEqual("queued", timeline.json()[0]["status"])

    def test_ingest_failure_enqueues_job(self) -> None:
        payload = build_failure().model_dump()
        response = self.client.post("/api/failures", json=payload)

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertIn("job_id", body["metadata"])
        self.assertEqual("detected", body["status"])

    def test_github_webhook_ingestion_queues_failed_run(self) -> None:
        failure = build_failure()
        failure.context = {"available": True}
        webhook_payload = {
            "action": "completed",
            "repository": {"full_name": failure.repository},
            "workflow_run": {
                "id": failure.workflow_run_id,
                "name": failure.workflow_name,
                "head_sha": failure.sha,
                "head_branch": failure.branch,
                "conclusion": "failure",
                "status": "completed",
                "event": "push",
                "display_title": failure.failed_step,
            },
        }

        with patch(
            "self_healing_agent.api.main.verify_github_webhook_signature",
            return_value=None,
        ), patch(
            "self_healing_agent.api.main.enrich_workflow_run_context",
            new=AsyncMock(return_value={"available": True, "failed_job": "tests", "failed_step": "failing step"}),
        ), patch(
            "self_healing_agent.api.main.normalize_workflow_run_failure",
            return_value=failure,
        ):
            response = self.client.post(
                "/api/webhooks/github",
                headers={
                    "x-hub-signature-256": "sha256=signature",
                    "x-github-event": "workflow_run",
                    "x-github-delivery": "delivery-1",
                },
                json=webhook_payload,
            )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("queued", body["status"])
        self.assertEqual(failure.workflow_run_id, body["workflow_run_id"])
        self.assertTrue(body["context_available"])

    def test_github_status_and_probe_endpoints(self) -> None:
        with patch(
            "self_healing_agent.api.main.github_integration_status",
            return_value={"configured": True, "reachable": True, "name": "test-app"},
        ), patch(
            "self_healing_agent.api.main.probe_github_repository",
            return_value={"repository": "acme/example", "reachable": True, "workflow_count": 2},
        ):
            status_response = self.client.get("/api/integrations/github/status")
            probe_response = self.client.get("/api/integrations/github/repositories/acme/example/probe")

        self.assertEqual(200, status_response.status_code)
        self.assertTrue(status_response.json()["reachable"])
        self.assertEqual(200, probe_response.status_code)
        self.assertEqual(2, probe_response.json()["workflow_count"])


if __name__ == "__main__":
    unittest.main()
