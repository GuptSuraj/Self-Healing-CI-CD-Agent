# Self-Healing CI/CD Agent

An AI-powered self-healing CI/CD platform that integrates with GitHub Actions to detect failures, analyze root cause, generate minimal safe fixes, validate them in an isolated sandbox, and open a pull request with evidence and confidence.

## Initial Monorepo Layout

- `apps/api`: FastAPI backend for GitHub ingestion, orchestration, metrics, and repair APIs
- `apps/dashboard`: Next.js dashboard shell for observability and operator views
- `packages/shared`: Shared TypeScript types for the dashboard
- `docs`: Architecture and delivery docs

## Core Product Capabilities

- GitHub Actions failure ingestion
- Agent-driven repair workflow with explicit safety gates
- Docker-based validation runner
- Pull request generation with explanation and confidence score
- Observability dashboard for failures, categories, repair quality, and time saved

## Currently Implemented Auto-Fix Scope

The backend currently supports deterministic bounded patch generation for:

- outdated GitHub Action versions in workflow snippets
- missing Python modules when a bounded `requirements.txt` snippet is available
- whitespace-only lint fixes in bounded changed-file snippets

The workflow blocks unsupported or unsafe fixes instead of generating broad edits.

## Current Validation Scope

The backend now generates structured Docker-based validation plans for supported fixes:

- patch applicability check with `git apply --check`
- targeted workflow, lint, dependency, or test commands based on failure category
- structured validation status and artifacts

Validation can now use either:

- an explicitly attached local git checkout via `failure.context.local_repo_path`
- an automatically synchronized checkout from GitHub when `SHCA_ENABLE_VALIDATION_REPO_SYNC=true`

## Current Writeback Scope

The backend can now prepare or create GitHub branches and draft pull requests after validation passes:

- proposed file contents are carried through the patch stage
- branch and commit creation use GitHub Git Data APIs
- PR title/body include root cause, validation, and confidence details
- writeback is gated by `SHCA_ENABLE_GITHUB_WRITEBACK`

If writeback is disabled or the candidate is incomplete, the workflow records a planned or blocked PR state instead of publishing changes.

## Current GitHub Verification Scope

The backend now exposes live GitHub integration probes for local verification:

- `GET /api/integrations/github/status`
- `GET /api/integrations/github/repositories/{owner}/{repo}/probe`

These endpoints let you verify app authentication, installation reachability, repository access, workflow visibility, and recent run visibility before you send real webhooks.

## Current LLM Patch Scope

The bounded LLM path now supports a real provider integration instead of a manual stub only:

- provider abstraction via `SHCA_LLM_PATCH_PROVIDER`
- OpenAI Responses API support through `SHCA_OPENAI_API_KEY`
- structured JSON-schema patch responses
- deterministic safety checks still applied after model output

## Current Queueing Scope

Webhook and manual failure ingestion now enqueue repair jobs instead of running the full workflow inline:

- repair runs are created in `detected` state
- repair jobs are stored in the database-backed queue
- a worker process claims queued jobs and executes the repair workflow
- API endpoints expose queued/running/completed/failed job state

## Current Worker Hardening

The worker now supports bounded retries and dead-letter handling:

- jobs track attempt count and max attempts
- failed jobs are requeued until the retry budget is exhausted
- exhausted jobs move to `dead_letter`
- worker health is exposed at `/api/worker/health`

## Planned Backend Flow

1. Receive GitHub webhook for a failed workflow run.
2. Fetch workflow logs, metadata, and bounded repository context.
3. Analyze the failure into a bounded context pack and fingerprint.
4. Classify the failure and determine whether it is safe to attempt repair.
5. Generate a minimal patch candidate.
6. Validate the candidate inside a sandbox.
7. Create a draft PR if validation succeeds and confidence is above threshold.
8. Persist audit events and dashboard metrics.

## Safety Principles

- Allowlist repositories before automation is enabled
- Limit changed files and diff size
- Block edits to protected paths
- Require validation before PR creation
- Never auto-merge
- Preserve audit logs for every decision

## Getting Started

This repository is an initial production-oriented scaffold.

Backend database setup:

1. Install API dependencies.
2. Run `alembic -c apps/api/alembic.ini upgrade head`.
3. Optionally set `SHCA_RUN_DB_MIGRATIONS_ON_STARTUP=true` to auto-apply migrations on boot.

Useful local env files:

- `apps/api/.env.example`
- `apps/dashboard/.env.example`

Convenience commands:

- `make api-install`
- `make api-migrate`
- `make api-run`
- `make worker-run`
- `make api-test`
- `make dashboard-install`
- `make dashboard-run`

Worker process:

1. Start the API service.
2. Run a worker loop from the API environment, for example:

```bash
python -c "from self_healing_agent.worker import run_worker_loop; run_worker_loop()"
```

Useful worker settings:

- `SHCA_WORKER_MAX_ATTEMPTS`
- `SHCA_WORKER_POLL_INTERVAL_SECONDS`

Useful GitHub settings:

- `SHCA_GITHUB_APP_ID`
- `SHCA_GITHUB_PRIVATE_KEY`
- `SHCA_GITHUB_INSTALLATION_ID`
- `SHCA_GITHUB_WEBHOOK_SECRET`
- `SHCA_ENABLE_GITHUB_WRITEBACK`

Useful validation settings:

- `SHCA_ENABLE_VALIDATION_EXECUTION`
- `SHCA_ENABLE_VALIDATION_REPO_SYNC`
- `SHCA_VALIDATION_CHECKOUT_ROOT`
- `SHCA_SANDBOX_IMAGE_NAME`

Useful LLM settings:

- `SHCA_ENABLE_LLM_PATCH_GENERATION`
- `SHCA_LLM_PATCH_PROVIDER`
- `SHCA_LLM_PATCH_MODEL`
- `SHCA_OPENAI_API_KEY`

The next implementation steps are:

- configure a GitHub App and point webhook deliveries to the API
- enable validation execution and test a real repository checkout
- enable writeback on a test repo and inspect the generated draft PR
