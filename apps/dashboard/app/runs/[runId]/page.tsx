import Link from "next/link";

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
    log_excerpt: string;
  };
  analysis?: {
    summary: string;
    likely_root_cause: string;
    category_signals: string[];
    evidence: string[];
  } | null;
  validation?: {
    status: string;
    summary: string;
    reproducible: boolean;
  } | null;
  confidence?: {
    overall: number;
  } | null;
  pull_request?: {
    status: string;
    url?: string | null;
    branch_name?: string | null;
  } | null;
};

type RunTimelineEntry = {
  sequence: number;
  event: string;
  payload: Record<string, unknown>;
};

type RunArtifact = {
  artifact_id: string;
  kind: string;
  name: string;
  content_type: string;
  size_bytes: number;
  preview: string;
};

async function fetchArtifactContent(runId: string, artifactId: string): Promise<string> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(
      `${baseUrl}/api/runs/${runId}/artifacts/${artifactId}/content`,
      { cache: "no-store" },
    );
    if (!response.ok) {
      return "";
    }
    return await response.text();
  } catch {
    return "";
  }
}

const fallbackRun: RepairRun = {
  run_id: "",
  status: "unknown",
  category: "unknown",
  decision: "unknown",
  failure: {
    repository: "unknown/unknown",
    workflow_run_id: 0,
    workflow_name: "unknown",
    branch: "unknown",
    failed_job: "unknown",
    failed_step: "unknown",
    log_excerpt: "",
  },
  analysis: null,
  validation: null,
  confidence: null,
  pull_request: null,
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

function prettyStatus(status: string) {
  return status.replaceAll("_", " ");
}

function payloadLines(payload: Record<string, unknown>) {
  return Object.entries(payload).slice(0, 6);
}

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  const run = await fetchJson<RepairRun>(`/api/runs/${runId}`, fallbackRun);
  const timeline = await fetchJson<RunTimelineEntry[]>(
    `/api/runs/${runId}/timeline`,
    [],
  );
  const artifacts = await fetchJson<RunArtifact[]>(
    `/api/runs/${runId}/artifacts`,
    [],
  );
  const validationArtifact = artifacts.find((artifact) => artifact.kind === "validation_log");
  const validationLog = validationArtifact
    ? await fetchArtifactContent(runId, validationArtifact.artifact_id)
    : "";

  return (
    <main className="page">
      <section className="page-header">
        <div>
          <span className="eyebrow">Run detail</span>
          <h1>{run.analysis?.summary ?? run.failure.failed_step}</h1>
          <p>{run.analysis?.likely_root_cause ?? "No analysis available for this run."}</p>
        </div>
        <Link className="detail-link" href="/">
          Back to dashboard
        </Link>
      </section>

      <section className="detail-hero">
        <article className="card">
          <div className="run-topline">
            <span className={`status status-${run.status.toLowerCase()}`}>
              {prettyStatus(run.status)}
            </span>
            <span className="mono">{run.failure.repository}</span>
          </div>
          <div className="detail-grid-compact">
            <div>
              <div className="metric-label">Workflow</div>
              <div>{run.failure.workflow_name}</div>
            </div>
            <div>
              <div className="metric-label">Branch</div>
              <div>{run.failure.branch}</div>
            </div>
            <div>
              <div className="metric-label">Failed job</div>
              <div>{run.failure.failed_job}</div>
            </div>
            <div>
              <div className="metric-label">Failed step</div>
              <div>{run.failure.failed_step}</div>
            </div>
          </div>
        </article>

        <article className="card">
          <h2 className="section-title">Outcome</h2>
          <div className="detail-grid-compact">
            <div>
              <div className="metric-label">Category</div>
              <div>{run.category}</div>
            </div>
            <div>
              <div className="metric-label">Decision</div>
              <div>{run.decision}</div>
            </div>
            <div>
              <div className="metric-label">Validation</div>
              <div>{run.validation?.status ?? "none"}</div>
            </div>
            <div>
              <div className="metric-label">Confidence</div>
              <div>{run.confidence?.overall ?? 0}</div>
            </div>
          </div>
          {run.pull_request?.url ? (
            <a className="detail-link" href={run.pull_request.url}>
              Open pull request
            </a>
          ) : (
            <div className="empty-state">No pull request created for this run.</div>
          )}
        </article>
      </section>

      <section className="two-column detail-grid">
        <article className="card">
          <h2 className="section-title">Evidence</h2>
          <div className="detail-list">
            {(run.analysis?.evidence ?? []).length === 0 ? (
              <div className="empty-state">No evidence captured.</div>
            ) : (
              (run.analysis?.evidence ?? []).map((item) => (
                <div className="detail-row" key={item}>
                  <span>{item}</span>
                </div>
              ))
            )}
          </div>
        </article>

        <article className="card">
          <h2 className="section-title">Timeline</h2>
          <div className="timeline">
            {timeline.length === 0 ? (
              <div className="empty-state">No audit timeline captured.</div>
            ) : (
              timeline.map((entry) => (
                <article className="timeline-item" key={`${entry.sequence}-${entry.event}`}>
                  <div className="timeline-head">
                    <strong>{entry.sequence}.</strong>
                    <span>{entry.event}</span>
                  </div>
                  <div className="timeline-payload">
                    {payloadLines(entry.payload).length === 0 ? (
                      <span className="empty-state">No payload</span>
                    ) : (
                      payloadLines(entry.payload).map(([key, value]) => (
                        <div className="payload-row" key={key}>
                          <span className="payload-key">{key}</span>
                          <span className="payload-value">
                            {typeof value === "string"
                              ? value
                              : JSON.stringify(value)}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </article>
              ))
            )}
          </div>
        </article>
      </section>

      <section className="two-column detail-grid">
        <article className="card">
          <h2 className="section-title">Artifacts</h2>
          <div className="detail-list">
            {artifacts.length === 0 ? (
              <div className="empty-state">No artifacts stored for this run.</div>
            ) : (
              artifacts.map((artifact) => (
                <article className="timeline-item" key={artifact.artifact_id}>
                  <div className="timeline-head">
                    <strong>{artifact.kind}</strong>
                    <span>{artifact.name}</span>
                  </div>
                  <div className="payload-row">
                    <span className="payload-key">size</span>
                    <span className="payload-value">{artifact.size_bytes} bytes</span>
                  </div>
                  <div className="artifact-preview">
                    {artifact.preview || "No preview available."}
                  </div>
                  <Link
                    className="detail-link"
                    href={`/runs/${runId}/artifacts/${artifact.artifact_id}`}
                  >
                    View full artifact
                  </Link>
                </article>
              ))
            )}
          </div>
        </article>

        <article className="card">
          <h2 className="section-title">Validation log excerpt</h2>
          <pre className="artifact-preview artifact-pre">
            {validationLog ||
              validationArtifact?.preview ||
              "No validation log stored."}
          </pre>
        </article>
      </section>
    </main>
  );
}
