# Architecture Overview

## Runtime Components

- `github-ingest`: receives GitHub webhooks and normalizes failure events
- `orchestrator`: executes the repair state machine and safety checks
- `analysis`: classifies failures and assembles repository context
- `patch-generation`: proposes minimal fixes
- `sandbox-validator`: reruns failing commands in an isolated container
- `pr-service`: creates branches, commits, and pull requests
- `observability`: aggregates metrics for operators and leaders

## Control Plane

- FastAPI exposes webhook, operator, and dashboard APIs
- Postgres persists failures, repair runs, artifacts, and PR outcomes
- Redis backs async job dispatch and short-lived coordination
- Object storage will store raw logs, diffs, and validation artifacts

## Agent Workflow

1. `ingest_failure`
2. `fetch_context`
3. `analyze_failure`
4. `classify_failure`
5. `safety_gate`
6. `generate_patch`
7. `validate_patch`
8. `score_confidence`
9. `create_pull_request`
10. `emit_metrics`

Each node must write a durable audit event so every repair attempt is explainable.

## Observability Dashboard

The dashboard is split into:

- operational health: failures detected, active repair runs, validation status
- repair quality: category breakdown, fix success rate, false positive rate
- impact: estimated time saved and top recurring issues

## Initial Boundaries

V1 intentionally supports only:

- GitHub Actions
- allowlisted repositories
- deterministic failure classes
- draft PR creation only
- no automatic merge or deployment actions

Current deterministic patch generators:

- workflow action version upgrades
- requirements.txt dependency additions for missing-module failures
- whitespace-only lint normalization

Current validation behavior:

- builds Docker-oriented validation plans
- selects targeted commands by failure category
- returns structured `planned` or `inconclusive` validation outcomes
- does not yet execute against a mounted target repository checkout

Current writeback behavior:

- attempts branch/commit/PR creation only after passed validation
- uses GitHub App credentials and GitHub Git Data APIs
- records `planned`, `blocked`, `failed`, or `created` PR states
- never auto-merges

Current execution model:

- API requests enqueue repair jobs into a database-backed queue
- worker processes claim queued jobs and execute the repair workflow asynchronously
- job state is queryable through API endpoints
