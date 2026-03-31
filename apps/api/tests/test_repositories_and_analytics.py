from __future__ import annotations

from datetime import date, timedelta
import unittest

from self_healing_agent.domain.models import (
    FailureAnalysis,
    FailureCategory,
    PullRequestInfo,
    RepairDecision,
    RepairRun,
    RunStatus,
    ValidationResult,
    WorkflowFailure,
)
from self_healing_agent.repositories.memory import InMemoryRepairRunRepository


def build_run(
    run_id: str,
    *,
    fingerprint: str,
    summary: str,
    category: FailureCategory,
    status: RunStatus,
    days_ago: int = 0,
    repository: str = "acme/example",
) -> RepairRun:
    created_at = (date.today() - timedelta(days=days_ago)).isoformat() + "T10:00:00"
    return RepairRun(
        run_id=run_id,
        status=status,
        failure=WorkflowFailure(
            repository=repository,
            workflow_run_id=1,
            workflow_name="ci",
            sha="1234567",
            branch="main",
            failed_job="tests",
            failed_step="failing step",
            log_excerpt="trace",
        ),
        analysis=FailureAnalysis(
            fingerprint=fingerprint,
            summary=summary,
            category_signals=[category.value],
            likely_root_cause="root cause",
            evidence=[],
            bounded_context={},
        ),
        category=category,
        decision=RepairDecision.REPAIR,
        validation=ValidationResult(
            status="passed",
            passed=True,
            reproducible=True,
            failure_observed=True,
            flaky=False,
            executed_commands=[],
            logs="",
        ),
        pull_request=PullRequestInfo(status="created"),
        metadata={"time_saved_hours": 0.5},
        created_at=created_at,
    )


class RepositoryAnalyticsTests(unittest.TestCase):
    def test_dashboard_trends_aggregate_recent_runs(self) -> None:
        repo = InMemoryRepairRunRepository()
        repo.upsert(build_run("1", fingerprint="fp-a", summary="issue a", category=FailureCategory.LINT, status=RunStatus.PR_CREATED, days_ago=0))
        repo.upsert(build_run("2", fingerprint="fp-b", summary="issue b", category=FailureCategory.TEST, status=RunStatus.VALIDATED, days_ago=1))

        trends = repo.dashboard_trends(days=7)

        self.assertEqual(7, trends.days)
        self.assertEqual(2, trends.failures_detected)
        self.assertEqual(2, trends.validated_fixes)
        self.assertEqual(2, trends.pull_requests_created)

    def test_recurring_issues_groups_by_fingerprint(self) -> None:
        repo = InMemoryRepairRunRepository()
        repo.upsert(build_run("1", fingerprint="fp-a", summary="same issue", category=FailureCategory.LINT, status=RunStatus.PR_CREATED, days_ago=0, repository="acme/one"))
        repo.upsert(build_run("2", fingerprint="fp-a", summary="same issue", category=FailureCategory.LINT, status=RunStatus.VALIDATED, days_ago=2, repository="acme/two"))
        repo.upsert(build_run("3", fingerprint="fp-b", summary="other issue", category=FailureCategory.TEST, status=RunStatus.VALIDATED, days_ago=1))

        report = repo.recurring_issues(days=30, limit=10)

        self.assertEqual(2, len(report.issues))
        self.assertEqual("fp-a", report.issues[0].fingerprint)
        self.assertEqual(2, report.issues[0].occurrences)
        self.assertEqual(["acme/one", "acme/two"], report.issues[0].repositories)
        self.assertTrue(report.issues[0].known_fixer_available)


if __name__ == "__main__":
    unittest.main()
