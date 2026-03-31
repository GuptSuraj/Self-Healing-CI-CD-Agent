# GitHub Webhook Integration

## Current Support

The backend currently accepts GitHub webhook deliveries at `/api/webhooks/github`.

Implemented behavior:

- verifies `X-Hub-Signature-256` using `SHCA_GITHUB_WEBHOOK_SECRET`
- accepts `workflow_run` events
- processes only `action=completed` with `conclusion=failure`
- normalizes the payload into the internal `WorkflowFailure` model
- attempts GitHub App context enrichment when app credentials are configured
- fetches bounded workflow evidence:
  - failed jobs and steps
  - changed file paths
  - workflow file snippet
  - changed file snippets
  - workflow run log excerpt from the GitHub log archive
- persists a repair run through the workflow engine

## Current Limitations

- does not yet fetch downloadable step logs
- does not yet fetch arbitrary repository dependency trees or import graphs
- does not yet handle pagination or GitHub rate limiting
- falls back to workflow-run metadata when app credentials are absent

## Required Next Step

Build the analysis/context layer that turns the collected evidence into a bounded root-cause context pack for the repair workflow.
