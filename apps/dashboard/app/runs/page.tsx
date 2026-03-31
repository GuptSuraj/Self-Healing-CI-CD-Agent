import Link from "next/link";

type RepairRun = {
  run_id: string;
  status: string;
  category: string;
  decision: string;
  failure: {
    repository: string;
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
  } | null;
  pull_request?: {
    status: string;
  } | null;
};

async function fetchRuns(query: string): Promise<RepairRun[]> {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${baseUrl}/api/runs${query}`, { cache: "no-store" });
    if (!response.ok) {
      return [];
    }
    return (await response.json()) as RepairRun[];
  } catch {
    return [];
  }
}

function prettyStatus(value: string) {
  return value.replaceAll("_", " ");
}

export default async function RunsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const query = new URLSearchParams();
  const repository = typeof params.repository === "string" ? params.repository : "";
  const status = typeof params.status === "string" ? params.status : "";
  const category = typeof params.category === "string" ? params.category : "";
  const search = typeof params.search === "string" ? params.search : "";

  if (repository) query.set("repository_name", repository);
  if (status) query.set("status", status);
  if (category) query.set("category", category);
  if (search) query.set("search", search);
  query.set("limit", "50");

  const runs = await fetchRuns(`?${query.toString()}`);

  return (
    <main className="page">
      <section className="page-header">
        <div>
          <span className="eyebrow">Run explorer</span>
          <h1>Repair runs</h1>
          <p>Filter runs by repository, status, category, or a failure/search term.</p>
        </div>
        <Link className="detail-link" href="/">
          Back to dashboard
        </Link>
      </section>

      <section className="card filter-card">
        <form className="filter-grid" method="get">
          <label className="field">
            <span>Repository</span>
            <input defaultValue={repository} name="repository" placeholder="owner/repo" />
          </label>
          <label className="field">
            <span>Status</span>
            <select defaultValue={status} name="status">
              <option value="">All</option>
              <option value="detected">Detected</option>
              <option value="analyzing">Analyzing</option>
              <option value="patch_generated">Patch generated</option>
              <option value="validated">Validated</option>
              <option value="pr_created">PR created</option>
              <option value="failed">Failed</option>
            </select>
          </label>
          <label className="field">
            <span>Category</span>
            <select defaultValue={category} name="category">
              <option value="">All</option>
              <option value="lint">Lint</option>
              <option value="dependency">Dependency</option>
              <option value="import">Import</option>
              <option value="test">Test</option>
              <option value="workflow">Workflow</option>
              <option value="flaky">Flaky</option>
              <option value="unsupported">Unsupported</option>
            </select>
          </label>
          <label className="field field-wide">
            <span>Search</span>
            <input
              defaultValue={search}
              name="search"
              placeholder="failed step, job, workflow, repository"
            />
          </label>
          <div className="filter-actions">
            <button className="button-primary" type="submit">
              Apply filters
            </button>
            <Link className="button-secondary" href="/runs">
              Reset
            </Link>
          </div>
        </form>
      </section>

      <section className="card list-card">
        <div className="section-header">
          <h2 className="section-title">Matching runs</h2>
          <span className="pill">{runs.length} shown</span>
        </div>
        <div className="run-list">
          {runs.length === 0 ? (
            <div className="empty-state">No runs matched the current filters.</div>
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
                  <span>{run.failure.workflow_name}</span>
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
      </section>
    </main>
  );
}
