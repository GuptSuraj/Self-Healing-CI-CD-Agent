from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from self_healing_agent.domain.models import (
    DashboardSummary,
    DashboardTrendPoint,
    DashboardTrends,
    RecurringIssueEntry,
    RecurringIssuesReport,
    RepairRun,
    RunArtifact,
)


class InMemoryRepairRunRepository:
    def __init__(self) -> None:
        self._runs: dict[str, RepairRun] = {}
        self._artifacts: dict[str, dict[str, tuple[RunArtifact, str]]] = {}

    def upsert(self, run: RepairRun) -> RepairRun:
        self._runs[run.run_id] = run
        return run

    def get(self, run_id: str) -> RepairRun | None:
        return self._runs.get(run_id)

    def list_runs(
        self,
        *,
        repository: str | None = None,
        status: str | None = None,
        category: str | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[RepairRun]:
        runs = list(self._runs.values())

        if repository:
            runs = [run for run in runs if run.failure.repository == repository]
        if status:
            runs = [run for run in runs if run.status.value == status]
        if category:
            runs = [run for run in runs if run.category.value == category]
        if search:
            needle = search.lower()
            runs = [
                run
                for run in runs
                if needle in run.failure.failed_step.lower()
                or needle in run.failure.failed_job.lower()
                or needle in run.failure.workflow_name.lower()
                or needle in run.failure.repository.lower()
                or (run.analysis and needle in run.analysis.summary.lower())
            ]

        runs.sort(key=lambda run: run.run_id, reverse=True)
        return runs[:limit] if limit is not None else runs

    def dashboard_summary(self) -> DashboardSummary:
        runs = self.list_runs()
        categories = Counter(run.category.value for run in runs)
        validated = [run for run in runs if run.validation and run.validation.passed]
        pr_created = [run for run in runs if run.status.value == "pr_created"]
        false_positives = [
            run for run in runs if run.metadata.get("false_positive", False)
        ]
        recurring = Counter(run.failure.failed_step for run in runs)
        return DashboardSummary(
            failures_detected=len(runs),
            categories=dict(categories),
            fix_success_rate=(len(validated) / len(runs)) if runs else 0.0,
            false_positive_rate=(len(false_positives) / len(pr_created))
            if pr_created
            else 0.0,
            time_saved_hours=round(sum(run.metadata.get("time_saved_hours", 0.0) for run in runs), 2),
            top_recurring_issues=[issue for issue, _ in recurring.most_common(5)],
        )

    def dashboard_trends(self, days: int = 7) -> DashboardTrends:
        clamped_days = max(1, min(days, 30))
        today = date.today()
        points: list[DashboardTrendPoint] = []

        for offset in range(clamped_days - 1, -1, -1):
            bucket_date = today - timedelta(days=offset)
            bucket_runs = [
                run
                for run in self._runs.values()
                if run.created_at and run.created_at.startswith(bucket_date.isoformat())
            ]
            points.append(
                DashboardTrendPoint(
                    date=bucket_date.isoformat(),
                    failures_detected=len(bucket_runs),
                    validated_fixes=sum(
                        1 for run in bucket_runs if run.validation and run.validation.passed
                    ),
                    pull_requests_created=sum(
                        1
                        for run in bucket_runs
                        if run.pull_request and run.pull_request.status == "created"
                    ),
                    time_saved_hours=round(
                        sum(float(run.metadata.get("time_saved_hours", 0.0)) for run in bucket_runs),
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
        cutoff = date.today() - timedelta(days=clamped_days - 1)
        buckets: dict[str, dict] = {}

        for run in self._runs.values():
            if not run.analysis or not run.created_at:
                continue
            if run.created_at[:10] < cutoff.isoformat():
                continue

            fingerprint = run.analysis.fingerprint
            bucket = buckets.setdefault(
                fingerprint,
                {
                    "summary": run.analysis.summary,
                    "category": run.category.value,
                    "occurrences": 0,
                    "repositories": set(),
                    "workflows": set(),
                    "last_seen": run.created_at,
                    "known_fixer_available": run.category.value
                    in {"lint", "dependency", "import", "workflow"},
                },
            )
            bucket["occurrences"] += 1
            bucket["repositories"].add(run.failure.repository)
            bucket["workflows"].add(run.failure.workflow_name)
            bucket["last_seen"] = max(bucket["last_seen"], run.created_at)

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
                    known_fixer_available=data["known_fixer_available"],
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
        artifact = RunArtifact(
            artifact_id=f"{run_id}-{len(self._artifacts.get(run_id, {})) + 1}",
            run_id=run_id,
            kind=kind,
            name=name,
            content_type=content_type,
            path=f"memory://{run_id}/{name}",
            size_bytes=len(content.encode("utf-8")),
            preview=content[:400],
        )
        bucket = self._artifacts.setdefault(run_id, {})
        bucket[artifact.artifact_id] = (artifact, content)
        return artifact

    def list_artifacts(self, run_id: str) -> list[RunArtifact]:
        bucket = self._artifacts.get(run_id, {})
        return [artifact for artifact, _ in bucket.values()]

    def get_artifact(self, run_id: str, artifact_id: str) -> RunArtifact | None:
        bucket = self._artifacts.get(run_id, {})
        stored = bucket.get(artifact_id)
        return stored[0] if stored else None

    def read_artifact(self, run_id: str, artifact_id: str) -> str | None:
        bucket = self._artifacts.get(run_id, {})
        stored = bucket.get(artifact_id)
        return stored[1] if stored else None
