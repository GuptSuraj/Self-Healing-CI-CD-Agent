import Link from "next/link";

type RepairJob = {
  job_id: string;
  run_id: string;
  status: string;
  error: string | null;
  attempts: number;
  max_attempts: number;
  payload: Record<string, unknown>;
};

type JobTimelineEntry = {
  sequence: number;
  status: string;
  error: string | null;
  attempts: number;
  timestamp: string | null;
  details: Record<string, unknown>;
};

async function fetchJson<T>(path: string, fallback: T): Promise<T> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${baseUrl}${path}`, { cache: "no-store" });
    if (!response.ok) {
      return fallback;
    }
    return (await response.json()) as T;
  } catch {
    return fallback;
  }
}

function prettyStatus(value: string) {
  return value.replaceAll("_", " ");
}

export default async function JobDetailPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  const job = await fetchJson<RepairJob | null>(`/api/jobs/${jobId}`, null);
  const timeline = await fetchJson<JobTimelineEntry[]>(`/api/jobs/${jobId}/timeline`, []);

  return (
    <main className="page">
      <section className="page-header">
        <div>
          <span className="eyebrow">Job detail</span>
          <h1>{job?.job_id ?? "Job not found"}</h1>
          <p>
            {job
              ? `Run ${job.run_id} · ${job.attempts} of ${job.max_attempts} attempts`
              : "The requested job is unavailable."}
          </p>
        </div>
        <div className="run-topline">
          {job ? (
            <Link className="detail-link" href={`/runs/${job.run_id}`}>
              Open related run
            </Link>
          ) : null}
          <Link className="detail-link" href="/jobs">
            Back to jobs
          </Link>
        </div>
      </section>

      {job ? (
        <>
          <section className="detail-hero">
            <article className="card">
              <div className="run-topline">
                <span className={`status status-${job.status}`}>{prettyStatus(job.status)}</span>
                <span className="mono">{job.job_id}</span>
              </div>
              <div className="detail-grid-compact">
                <div>
                  <div className="metric-label">Run</div>
                  <div className="mono">{job.run_id}</div>
                </div>
                <div>
                  <div className="metric-label">Attempts</div>
                  <div>
                    {job.attempts} / {job.max_attempts}
                  </div>
                </div>
                <div>
                  <div className="metric-label">Current error</div>
                  <div>{job.error ?? "none"}</div>
                </div>
              </div>
            </article>

            <article className="card">
              <h2 className="section-title">Payload</h2>
              <pre className="artifact-preview artifact-pre">
                {JSON.stringify(job.payload, null, 2)}
              </pre>
            </article>
          </section>

          <section className="card list-card">
            <div className="section-header">
              <h2 className="section-title">Retry timeline</h2>
              <span className="pill">{timeline.length} events</span>
            </div>
            <div className="timeline">
              {timeline.length === 0 ? (
                <div className="empty-state">No job history captured.</div>
              ) : (
                timeline.map((entry) => (
                  <article className="timeline-item" key={`${entry.sequence}-${entry.status}`}>
                    <div className="timeline-head">
                      <strong>{entry.sequence}.</strong>
                      <span className={`status status-${entry.status}`}>
                        {prettyStatus(entry.status)}
                      </span>
                    </div>
                    <div className="payload-row">
                      <span className="payload-key">attempts</span>
                      <span className="payload-value">{entry.attempts}</span>
                    </div>
                    <div className="payload-row">
                      <span className="payload-key">timestamp</span>
                      <span className="payload-value">{entry.timestamp ?? "unknown"}</span>
                    </div>
                    <div className="payload-row">
                      <span className="payload-key">error</span>
                      <span className="payload-value">{entry.error ?? "none"}</span>
                    </div>
                    <div className="payload-row">
                      <span className="payload-key">details</span>
                      <span className="payload-value">
                        {JSON.stringify(entry.details)}
                      </span>
                    </div>
                  </article>
                ))
              )}
            </div>
          </section>
        </>
      ) : (
        <section className="card">
          <div className="empty-state">Job not found.</div>
        </section>
      )}
    </main>
  );
}
