import Link from "next/link";

type DashboardSummary = {
  failures_detected: number;
  categories: Record<string, number>;
  fix_success_rate: number;
  false_positive_rate: number;
  time_saved_hours: number;
  top_recurring_issues: string[];
};

type DashboardTrendPoint = {
  date: string;
  failures_detected: number;
  validated_fixes: number;
  pull_requests_created: number;
  time_saved_hours: number;
};

type DashboardTrends = {
  days: number;
  points: DashboardTrendPoint[];
  failures_detected: number;
  validated_fixes: number;
  pull_requests_created: number;
  time_saved_hours: number;
};

type RepairJob = {
  job_id: string;
  run_id: string;
  status: "queued" | "running" | "completed" | "failed";
  payload: Record<string, unknown>;
  error: string | null;
};

type RepairRun = {
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
};

type Overview = {
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

const fallbackOverview: Overview = {
  summary: {
    failures_detected: 0,
    categories: {
      lint: 0,
      dependency: 0,
      import: 0,
      test: 0,
      workflow: 0,
    },
    fix_success_rate: 0,
    false_positive_rate: 0,
    time_saved_hours: 0,
    top_recurring_issues: ["No failure patterns captured yet"],
  },
  job_counts: {
    queued: 0,
    running: 0,
    completed: 0,
    failed: 0,
  },
  recent_runs: [],
  recent_jobs: [],
};

const fallbackTrends: DashboardTrends = {
  days: 7,
  points: [],
  failures_detected: 0,
  validated_fixes: 0,
  pull_requests_created: 0,
  time_saved_hours: 0,
};

async function getOverview(): Promise<Overview> {
  const baseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  try {
    const response = await fetch(`${baseUrl}/api/dashboard/overview`, {
      cache: "no-store",
    });
    if (!response.ok) {
      return fallbackOverview;
    }
    return (await response.json()) as Overview;
  } catch {
    return fallbackOverview;
  }
}

async function getTrends(days: number): Promise<DashboardTrends> {
  const baseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

  try {
    const response = await fetch(`${baseUrl}/api/dashboard/trends?days=${days}`, {
      cache: "no-store",
    });
    if (!response.ok) {
      return fallbackTrends;
    }
    return (await response.json()) as DashboardTrends;
  } catch {
    return fallbackTrends;
  }
}

function prettyStatus(status: string) {
  return status.replaceAll("_", " ");
}

function maxFailures(points: DashboardTrendPoint[]) {
  return Math.max(1, ...points.map((point) => point.failures_detected));
}

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const requestedDays =
    typeof params.days === "string" ? Number.parseInt(params.days, 10) : 7;
  const days = Number.isFinite(requestedDays) ? Math.min(Math.max(requestedDays, 7), 30) : 7;
  const overview = await getOverview();
  const trends = await getTrends(days);
  const summary = overview.summary;
  const categories = Object.entries(summary.categories);
  const jobs = overview.recent_jobs;
  const runs = overview.recent_runs;
  const trendMax = maxFailures(trends.points);

  return (
    <main className="page">
      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">AI-powered CI resilience</span>
          <h1>Self-healing workflows with operator-grade visibility.</h1>
          <p>
            Track queued repairs, inspect validation outcomes, and surface the
            recurring CI failure patterns that are costing engineering time.
          </p>
        </div>
        <div className="hero-panel card">
          <div className="metric-label">Queue health</div>
          <div className="queue-grid">
            <div>
              <div className="mini-label">Queued</div>
              <div className="mini-value">{overview.job_counts.queued}</div>
            </div>
            <div>
              <div className="mini-label">Running</div>
              <div className="mini-value accent">{overview.job_counts.running}</div>
            </div>
            <div>
              <div className="mini-label">Completed</div>
              <div className="mini-value">{overview.job_counts.completed}</div>
            </div>
            <div>
              <div className="mini-label">Failed</div>
              <div className="mini-value danger">{overview.job_counts.failed}</div>
            </div>
          </div>
        </div>
      </section>

      <section className="stats-grid">
        <article className="card">
          <div className="metric-label">Failures detected</div>
          <div className="metric-value">{summary.failures_detected}</div>
        </article>
        <article className="card">
          <div className="metric-label">Fix success rate</div>
          <div className="metric-value">
            {(summary.fix_success_rate * 100).toFixed(0)}%
          </div>
        </article>
        <article className="card">
          <div className="metric-label">False positive rate</div>
          <div className="metric-value danger">
            {(summary.false_positive_rate * 100).toFixed(0)}%
          </div>
        </article>
        <article className="card">
          <div className="metric-label">Estimated time saved</div>
          <div className="metric-value">{summary.time_saved_hours.toFixed(1)}h</div>
        </article>
      </section>

      <section className="card trend-card">
        <div className="section-header">
          <div>
            <h2 className="section-title">Trend view</h2>
            <div className="metric-label">
              Failures, validated fixes, PR creation, and time saved over the selected window.
            </div>
          </div>
          <div className="range-switch">
            {[7, 14, 30].map((option) => (
              <Link
                className={`range-chip ${days === option ? "range-chip-active" : ""}`}
                href={`/?days=${option}`}
                key={option}
              >
                {option}d
              </Link>
            ))}
          </div>
        </div>
        <div className="stats-grid">
          <article className="trend-stat">
            <div className="metric-label">Failures in range</div>
            <div className="metric-value">{trends.failures_detected}</div>
          </article>
          <article className="trend-stat">
            <div className="metric-label">Validated fixes</div>
            <div className="metric-value">{trends.validated_fixes}</div>
          </article>
          <article className="trend-stat">
            <div className="metric-label">PRs created</div>
            <div className="metric-value">{trends.pull_requests_created}</div>
          </article>
          <article className="trend-stat">
            <div className="metric-label">Time saved in range</div>
            <div className="metric-value">{trends.time_saved_hours.toFixed(1)}h</div>
          </article>
        </div>
        <div className="trend-bars">
          {trends.points.length === 0 ? (
            <div className="empty-state">No trend data available yet.</div>
          ) : (
            trends.points.map((point) => (
              <article className="trend-point" key={point.date}>
                <div className="trend-bar-stack">
                  <div
                    className="trend-bar"
                    style={{
                      height: `${Math.max(8, (point.failures_detected / trendMax) * 180)}px`,
                    }}
                  />
                  <div
                    className="trend-overlay"
                    style={{
                      height: `${Math.max(4, (point.validated_fixes / trendMax) * 180)}px`,
                    }}
                  />
                </div>
                <div className="trend-date">{point.date.slice(5)}</div>
                <div className="trend-meta">
                  <span>F {point.failures_detected}</span>
                  <span>V {point.validated_fixes}</span>
                  <span>P {point.pull_requests_created}</span>
                </div>
              </article>
            ))
          )}
        </div>
      </section>

      <section className="two-column">
        <article className="card">
          <h2 className="section-title">Failure categories</h2>
          <ul className="category-list">
            {categories.map(([name, value]) => (
              <li className="row" key={name}>
                <span>{name}</span>
                <strong>{value}</strong>
              </li>
            ))}
          </ul>
        </article>
        <article className="card">
          <div className="section-header">
            <h2 className="section-title">Recurring issues</h2>
            <Link className="detail-link" href="/issues">
              View all issues
            </Link>
          </div>
          <ul className="issue-list">
            {summary.top_recurring_issues.map((issue) => (
              <li className="row" key={issue}>
                <span>{issue}</span>
              </li>
            ))}
          </ul>
        </article>
      </section>

      <section className="two-column detail-grid">
        <article className="card">
          <div className="section-header">
            <h2 className="section-title">Recent jobs</h2>
            <Link className="detail-link" href="/jobs">
              View all jobs
            </Link>
          </div>
          <div className="table">
            <div className="table-head">
              <span>Status</span>
              <span>Run</span>
              <span>Job</span>
            </div>
            {jobs.length === 0 ? (
              <div className="empty-state">No jobs queued yet.</div>
            ) : (
              jobs.map((job) => (
                <div className="table-row" key={job.job_id}>
                  <span className={`status status-${job.status}`}>
                    {prettyStatus(job.status)}
                  </span>
                  <span className="mono">{job.run_id.slice(0, 8)}</span>
                  <span className="mono">{job.job_id.slice(0, 8)}</span>
                </div>
              ))
            )}
          </div>
        </article>

        <article className="card">
          <div className="section-header">
            <h2 className="section-title">Recent runs</h2>
            <Link className="detail-link" href="/runs">
              View all runs
            </Link>
          </div>
          <div className="run-list">
            {runs.length === 0 ? (
              <div className="empty-state">No repair runs detected yet.</div>
            ) : (
              runs.map((run) => (
                <article className="run-item" key={run.run_id}>
                  <div className="run-topline">
                    <span className={`status status-${run.status.toLowerCase()}`}>
                      {prettyStatus(run.status)}
                    </span>
                    <span className="mono">{run.failure.repository}</span>
                  </div>
                  <h3>{run.analysis?.summary ?? run.failure.failed_step}</h3>
                  <p>{run.analysis?.likely_root_cause ?? "Analysis pending."}</p>
                  <div className="run-meta">
                    <span>{run.category}</span>
                    <span>{run.validation?.status ?? "no validation"}</span>
                    <span>{run.pull_request?.status ?? "no pr"}</span>
                  </div>
                  <Link className="detail-link" href={`/runs/${run.run_id}`}>
                    View run details
                  </Link>
                </article>
              ))
            )}
          </div>
        </article>
      </section>
    </main>
  );
}
