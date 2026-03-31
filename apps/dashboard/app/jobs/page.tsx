import Link from "next/link";

type RepairJob = {
  job_id: string;
  run_id: string;
  status: string;
  error: string | null;
  attempts: number;
  max_attempts: number;
};

async function fetchJobs(query: string): Promise<RepairJob[]> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${baseUrl}/api/jobs${query}`, { cache: "no-store" });
    if (!response.ok) {
      return [];
    }
    return (await response.json()) as RepairJob[];
  } catch {
    return [];
  }
}

function prettyStatus(value: string) {
  return value.replaceAll("_", " ");
}

export default async function JobsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const status = typeof params.status === "string" ? params.status : "";
  const runId = typeof params.run_id === "string" ? params.run_id : "";
  const search = typeof params.search === "string" ? params.search : "";

  const query = new URLSearchParams();
  if (status) query.set("status", status);
  if (runId) query.set("run_id", runId);
  if (search) query.set("search", search);
  query.set("limit", "50");

  const jobs = await fetchJobs(`?${query.toString()}`);

  return (
    <main className="page">
      <section className="page-header">
        <div>
          <span className="eyebrow">Queue explorer</span>
          <h1>Repair jobs</h1>
          <p>Inspect queued, running, failed, and dead-letter jobs across the worker fleet.</p>
        </div>
        <Link className="detail-link" href="/">
          Back to dashboard
        </Link>
      </section>

      <section className="card filter-card">
        <form className="filter-grid" method="get">
          <label className="field">
            <span>Status</span>
            <select defaultValue={status} name="status">
              <option value="">All</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="dead_letter">Dead letter</option>
            </select>
          </label>
          <label className="field">
            <span>Run ID</span>
            <input defaultValue={runId} name="run_id" placeholder="Exact run id" />
          </label>
          <label className="field field-wide">
            <span>Search</span>
            <input defaultValue={search} name="search" placeholder="job id, run id, error text" />
          </label>
          <div className="filter-actions">
            <button className="button-primary" type="submit">
              Apply filters
            </button>
            <Link className="button-secondary" href="/jobs">
              Reset
            </Link>
          </div>
        </form>
      </section>

      <section className="card list-card">
        <div className="section-header">
          <h2 className="section-title">Matching jobs</h2>
          <span className="pill">{jobs.length} shown</span>
        </div>
        <div className="job-list">
          {jobs.length === 0 ? (
            <div className="empty-state">No jobs matched the current filters.</div>
          ) : (
            jobs.map((job) => (
              <article className="timeline-item" key={job.job_id}>
                <div className="run-topline">
                  <span className={`status status-${job.status}`}>{prettyStatus(job.status)}</span>
                  <span className="mono">{job.job_id}</span>
                </div>
                <div className="payload-row">
                  <span className="payload-key">run</span>
                  <span className="payload-value">{job.run_id}</span>
                </div>
                <div className="payload-row">
                  <span className="payload-key">attempts</span>
                  <span className="payload-value">
                    {job.attempts} / {job.max_attempts}
                  </span>
                </div>
                <div className="payload-row">
                  <span className="payload-key">error</span>
                  <span className="payload-value">{job.error ?? "none"}</span>
                </div>
                <Link className="detail-link" href={`/runs/${job.run_id}`}>
                  Open related run
                </Link>
                <Link className="detail-link" href={`/jobs/${job.job_id}`}>
                  View job details
                </Link>
              </article>
            ))
          )}
        </div>
      </section>
    </main>
  );
}
