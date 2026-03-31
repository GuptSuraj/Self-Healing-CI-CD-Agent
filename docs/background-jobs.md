# Background Jobs

The API now separates ingestion from execution.

## Flow

1. A failed workflow is ingested through `/api/webhooks/github` or `/api/failures`.
2. A `repair_runs` row is created in `detected` state.
3. A `repair_jobs` row is enqueued in `queued` state.
4. A worker claims the next queued job, marks it `running`, and executes the repair workflow.
5. On failure, the worker requeues the job until `max_attempts` is reached.
6. Exhausted jobs move to `dead_letter`.
7. Successful jobs are marked `completed`.

## Endpoints

- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/worker/health`

## Worker Entry Point

Run the worker loop from the API environment:

```bash
python -c "from self_healing_agent.worker import run_worker_loop; run_worker_loop()"
```

## Retry Settings

- `SHCA_WORKER_MAX_ATTEMPTS`
- `SHCA_WORKER_POLL_INTERVAL_SECONDS`

## Migration

Apply the latest migration to create and evolve the `repair_jobs` table:

```bash
alembic -c apps/api/alembic.ini upgrade head
```
