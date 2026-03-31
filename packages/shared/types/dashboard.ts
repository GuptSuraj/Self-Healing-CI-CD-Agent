export type DashboardSummary = {
  failures_detected: number;
  categories: Record<string, number>;
  fix_success_rate: number;
  false_positive_rate: number;
  time_saved_hours: number;
  top_recurring_issues: string[];
};

export type DashboardTrendPoint = {
  date: string;
  failures_detected: number;
  validated_fixes: number;
  pull_requests_created: number;
  time_saved_hours: number;
};

export type DashboardTrends = {
  days: number;
  points: DashboardTrendPoint[];
  failures_detected: number;
  validated_fixes: number;
  pull_requests_created: number;
  time_saved_hours: number;
};

export type RecurringIssueEntry = {
  fingerprint: string;
  summary: string;
  category: string;
  occurrences: number;
  repositories: string[];
  workflows: string[];
  last_seen: string | null;
  known_fixer_available: boolean;
};

export type RecurringIssuesReport = {
  days: number;
  issues: RecurringIssueEntry[];
};

export type RepairJob = {
  job_id: string;
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  payload: Record<string, unknown>;
  error: string | null;
  created_at?: string | null;
};

export type RepairRun = {
  run_id: string;
  status: string;
  category: string;
  decision: string;
  failure: {
    repository: string;
    workflow_run_id: number;
    workflow_name: string;
    branch: string;
    failed_job: string;
    failed_step: string;
  };
  analysis?: {
    summary: string;
    likely_root_cause: string;
  } | null;
  validation?: {
    status: string;
    summary: string;
  } | null;
  pull_request?: {
    status: string;
    url?: string | null;
  } | null;
  metadata: Record<string, unknown>;
  created_at?: string | null;
};

export type DashboardOverview = {
  summary: DashboardSummary;
  job_counts: {
    queued: number;
    running: number;
    completed: number;
    failed: number;
  };
  recent_runs: RepairRun[];
  recent_jobs: RepairJob[];
};
