from __future__ import annotations

from typing import Protocol

from self_healing_agent.domain.models import (
    DashboardSummary,
    DashboardTrends,
    RecurringIssuesReport,
    RepairRun,
    RunArtifact,
)


class RepairRunRepository(Protocol):
    def upsert(self, run: RepairRun) -> RepairRun:
        ...

    def get(self, run_id: str) -> RepairRun | None:
        ...

    def list_runs(
        self,
        *,
        repository: str | None = None,
        status: str | None = None,
        category: str | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[RepairRun]:
        ...

    def dashboard_summary(self) -> DashboardSummary:
        ...

    def dashboard_trends(self, days: int = 7) -> DashboardTrends:
        ...

    def recurring_issues(self, days: int = 30, limit: int = 20) -> RecurringIssuesReport:
        ...

    def save_artifact(
        self,
        run_id: str,
        kind: str,
        name: str,
        content: str,
        content_type: str = "text/plain",
    ) -> RunArtifact:
        ...

    def list_artifacts(self, run_id: str) -> list[RunArtifact]:
        ...

    def get_artifact(self, run_id: str, artifact_id: str) -> RunArtifact | None:
        ...

    def read_artifact(self, run_id: str, artifact_id: str) -> str | None:
        ...
