from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class FailureCategory(str, Enum):
    LINT = "lint"
    DEPENDENCY = "dependency"
    IMPORT = "import"
    TEST = "test"
    WORKFLOW = "workflow"
    FLAKY = "flaky"
    UNSUPPORTED = "unsupported"


class RepairDecision(str, Enum):
    SKIP = "skip"
    REPAIR = "repair"
    HUMAN_REVIEW = "human_review"


class RunStatus(str, Enum):
    DETECTED = "detected"
    ANALYZING = "analyzing"
    PATCH_GENERATED = "patch_generated"
    VALIDATED = "validated"
    PR_CREATED = "pr_created"
    FAILED = "failed"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class WorkflowFailure(BaseModel):
    repository: str
    workflow_run_id: int
    workflow_name: str
    sha: str
    branch: str
    failed_job: str
    failed_step: str
    log_excerpt: str
    html_url: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class FailureAnalysis(BaseModel):
    fingerprint: str
    summary: str
    category_signals: list[str] = Field(default_factory=list)
    likely_root_cause: str
    evidence: list[str] = Field(default_factory=list)
    bounded_context: dict[str, Any] = Field(default_factory=dict)


class RepairPolicy(BaseModel):
    allowed_repositories: list[str] = Field(default_factory=lambda: ["*"])
    blocked_categories: list[str] = Field(default_factory=lambda: ["flaky", "unsupported"])
    allowed_patch_generation_sources: list[str] = Field(
        default_factory=lambda: ["deterministic", "llm"]
    )
    max_changed_files: int = 3
    max_changed_lines: int = 80
    protected_paths: list[str] = Field(
        default_factory=lambda: [".github/secrets", "infra/prod", "terraform/prod"]
    )
    draft_pr_only: bool = True
    auto_merge_enabled: bool = False
    min_confidence_for_draft_pr: float = 0.65
    min_confidence_for_pr: float = 0.85
    require_known_fixer_for_pr: bool = False


class PatchCandidate(BaseModel):
    summary: str
    diff: str
    changed_files: list[str]
    changed_lines: int
    rationale: str
    strategy: str = "unsupported"
    generation_source: str = "deterministic"
    safe_to_apply: bool = False
    warnings: list[str] = Field(default_factory=list)
    proposed_file_contents: dict[str, str] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    status: str = "inconclusive"
    passed: bool
    executed_commands: list[str]
    logs: str
    artifacts: list[str] = Field(default_factory=list)
    summary: str = ""
    reproducible: bool = False
    failure_observed: bool = False
    flaky: bool = False


class ConfidenceScore(BaseModel):
    overall: float
    root_cause_certainty: float
    patch_minimality: float
    validation_strength: float
    scope_risk: float
    notes: list[str] = Field(default_factory=list)


class PullRequestInfo(BaseModel):
    status: str = "not_attempted"
    branch_name: str | None = None
    title: str | None = None
    body: str | None = None
    url: str | None = None
    number: int | None = None
    draft: bool = True
    warnings: list[str] = Field(default_factory=list)


class RunArtifact(BaseModel):
    artifact_id: str
    run_id: str
    kind: str
    name: str
    content_type: str = "text/plain"
    path: str
    size_bytes: int
    preview: str = ""


class RepairRun(BaseModel):
    run_id: str
    status: RunStatus
    failure: WorkflowFailure
    analysis: FailureAnalysis | None = None
    category: FailureCategory
    decision: RepairDecision
    patch: PatchCandidate | None = None
    validation: ValidationResult | None = None
    confidence: ConfidenceScore | None = None
    pull_request: PullRequestInfo | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None


class AuditEvent(BaseModel):
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


class RepairJob(BaseModel):
    job_id: str
    run_id: str
    status: JobStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    attempts: int = 0
    max_attempts: int = 3
    created_at: str | None = None


class JobTimelineEntry(BaseModel):
    sequence: int
    status: str
    error: str | None = None
    attempts: int = 0
    timestamp: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class JobCounts(BaseModel):
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0


class DashboardOverview(BaseModel):
    summary: DashboardSummary
    job_counts: JobCounts
    recent_runs: list[RepairRun] = Field(default_factory=list)
    recent_jobs: list[RepairJob] = Field(default_factory=list)


class RunTimelineEntry(BaseModel):
    sequence: int
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)


class DashboardSummary(BaseModel):
    failures_detected: int
    categories: dict[str, int]
    fix_success_rate: float
    false_positive_rate: float
    time_saved_hours: float
    top_recurring_issues: list[str]


class DashboardTrendPoint(BaseModel):
    date: str
    failures_detected: int = 0
    validated_fixes: int = 0
    pull_requests_created: int = 0
    time_saved_hours: float = 0.0


class DashboardTrends(BaseModel):
    days: int
    points: list[DashboardTrendPoint] = Field(default_factory=list)
    failures_detected: int = 0
    validated_fixes: int = 0
    pull_requests_created: int = 0
    time_saved_hours: float = 0.0


class RecurringIssueEntry(BaseModel):
    fingerprint: str
    summary: str
    category: str
    occurrences: int = 0
    repositories: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    last_seen: str | None = None
    known_fixer_available: bool = False


class RecurringIssuesReport(BaseModel):
    days: int
    issues: list[RecurringIssueEntry] = Field(default_factory=list)
