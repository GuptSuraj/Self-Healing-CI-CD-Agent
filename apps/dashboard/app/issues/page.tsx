import Link from "next/link";

type RecurringIssueEntry = {
  fingerprint: string;
  summary: string;
  category: string;
  occurrences: number;
  repositories: string[];
  workflows: string[];
  last_seen: string | null;
  known_fixer_available: boolean;
};

type RecurringIssuesReport = {
  days: number;
  issues: RecurringIssueEntry[];
};

async function fetchIssues(days: number, limit: number): Promise<RecurringIssuesReport> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(
      `${baseUrl}/api/dashboard/recurring-issues?days=${days}&limit=${limit}`,
      { cache: "no-store" },
    );
    if (!response.ok) {
      return { days, issues: [] };
    }
    return (await response.json()) as RecurringIssuesReport;
  } catch {
    return { days, issues: [] };
  }
}

export default async function IssuesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const requestedDays =
    typeof params.days === "string" ? Number.parseInt(params.days, 10) : 30;
  const days = Number.isFinite(requestedDays) ? Math.min(Math.max(requestedDays, 7), 90) : 30;
  const issues = await fetchIssues(days, 30);

  return (
    <main className="page">
      <section className="page-header">
        <div>
          <span className="eyebrow">Recurring issue explorer</span>
          <h1>Repeated CI failure signatures</h1>
          <p>Group failures by normalized fingerprint to see what keeps coming back.</p>
        </div>
        <div className="run-topline">
          {[7, 30, 90].map((option) => (
            <Link
              className={`range-chip ${days === option ? "range-chip-active" : ""}`}
              href={`/issues?days=${option}`}
              key={option}
            >
              {option}d
            </Link>
          ))}
          <Link className="detail-link" href="/">
            Back to dashboard
          </Link>
        </div>
      </section>

      <section className="card list-card">
        <div className="section-header">
          <h2 className="section-title">Grouped signatures</h2>
          <span className="pill">{issues.issues.length} issues</span>
        </div>
        <div className="timeline">
          {issues.issues.length === 0 ? (
            <div className="empty-state">No recurring issues found for the selected range.</div>
          ) : (
            issues.issues.map((issue) => (
              <article className="timeline-item" key={issue.fingerprint}>
                <div className="timeline-head">
                  <strong>{issue.summary}</strong>
                  <span className={`status status-${issue.category}`}>{issue.category}</span>
                </div>
                <div className="payload-row">
                  <span className="payload-key">fingerprint</span>
                  <span className="payload-value">{issue.fingerprint}</span>
                </div>
                <div className="payload-row">
                  <span className="payload-key">occurrences</span>
                  <span className="payload-value">{issue.occurrences}</span>
                </div>
                <div className="payload-row">
                  <span className="payload-key">repositories</span>
                  <span className="payload-value">{issue.repositories.join(", ") || "none"}</span>
                </div>
                <div className="payload-row">
                  <span className="payload-key">workflows</span>
                  <span className="payload-value">{issue.workflows.join(", ") || "none"}</span>
                </div>
                <div className="payload-row">
                  <span className="payload-key">last seen</span>
                  <span className="payload-value">{issue.last_seen ?? "unknown"}</span>
                </div>
                <div className="payload-row">
                  <span className="payload-key">known fixer</span>
                  <span className="payload-value">
                    {issue.known_fixer_available ? "available" : "not yet"}
                  </span>
                </div>
              </article>
            ))
          )}
        </div>
      </section>
    </main>
  );
}
