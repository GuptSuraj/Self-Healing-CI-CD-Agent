from __future__ import annotations

import time
from typing import Any

import httpx

from self_healing_agent.config import settings
from self_healing_agent.domain.models import (
    ConfidenceScore,
    FailureAnalysis,
    PatchCandidate,
    PullRequestInfo,
    ValidationResult,
    WorkflowFailure,
)
from self_healing_agent.services.github import (
    fetch_installation_token_sync,
    github_app_configured,
    parse_full_name,
    resolve_installation_id_sync,
)


RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


def create_pull_request_for_fix(
    failure: WorkflowFailure,
    analysis: FailureAnalysis,
    patch: PatchCandidate,
    validation: ValidationResult,
    confidence: ConfidenceScore,
) -> PullRequestInfo:
    title = build_pr_title(failure, patch)
    body = build_pr_body(failure, analysis, patch, validation, confidence)
    draft = confidence.overall < settings.min_confidence_for_pr

    if not validation.passed:
        return PullRequestInfo(
            status="blocked",
            title=title,
            body=body,
            draft=draft,
            warnings=["Validation must pass before PR creation is attempted."],
        )

    if not settings.enable_github_writeback:
        return PullRequestInfo(
            status="planned",
            draft=True,
            title=title,
            body=body,
            warnings=["GitHub writeback is disabled. Set SHCA_ENABLE_GITHUB_WRITEBACK=true."],
        )

    if not github_app_configured():
        return PullRequestInfo(
            status="blocked",
            title=title,
            body=body,
            draft=draft,
            warnings=["GitHub App credentials are not configured for writeback."],
        )

    if not patch.proposed_file_contents:
        return PullRequestInfo(
            status="blocked",
            title=title,
            body=body,
            draft=draft,
            warnings=["Patch does not include proposed file contents for branch creation."],
        )

    if any("...[truncated]..." in content for content in patch.proposed_file_contents.values()):
        return PullRequestInfo(
            status="blocked",
            title=title,
            body=body,
            draft=draft,
            warnings=["Patch content appears truncated and cannot be safely written back."],
        )

    owner, repo = parse_full_name(failure.repository)
    branch_name = build_branch_name(analysis.fingerprint, failure.sha)

    try:
        with httpx.Client(
            base_url=settings.github_api_url,
            headers={"Accept": "application/vnd.github+json"},
            timeout=20.0,
        ) as client:
            installation_id = resolve_installation_id_sync(
                client,
                owner,
                repo,
                failure.context.get("installation_id"),
            )
            if installation_id is None:
                return PullRequestInfo(
                    status="blocked",
                    title=title,
                    body=body,
                    draft=draft,
                    warnings=["GitHub installation could not be resolved for writeback."],
                )

            token = fetch_installation_token_sync(client, installation_id)
            client.headers["Authorization"] = f"Bearer {token}"

            branch_name = ensure_unique_branch_name(
                client=client,
                owner=owner,
                repo=repo,
                desired_branch_name=branch_name,
            )
            commit_sha = create_commit_for_patch(
                client=client,
                owner=owner,
                repo=repo,
                base_sha=failure.sha,
                branch_name=branch_name,
                patch=patch,
                message=title,
            )
            pr_payload = create_pull_request_sync(
                client=client,
                owner=owner,
                repo=repo,
                title=title,
                body=body,
                head=branch_name,
                base=failure.branch,
                draft=draft,
            )

            return PullRequestInfo(
                status="created",
                branch_name=branch_name,
                title=title,
                body=body,
                url=pr_payload.get("html_url"),
                number=pr_payload.get("number"),
                draft=draft,
                warnings=[f"Created commit {commit_sha} on branch {branch_name}."],
            )
    except httpx.HTTPError as error:
        return PullRequestInfo(
            status="failed",
            branch_name=branch_name,
            title=title,
            body=body,
            draft=draft,
            warnings=[f"GitHub writeback failed: {error}"],
        )


def build_branch_name(fingerprint: str, sha: str) -> str:
    return f"shca/{fingerprint}-{sha[:7] or 'manual'}"


def build_pr_title(failure: WorkflowFailure, patch: PatchCandidate) -> str:
    return f"fix(ci): {patch.summary.lower()}"


def build_pr_body(
    failure: WorkflowFailure,
    analysis: FailureAnalysis,
    patch: PatchCandidate,
    validation: ValidationResult,
    confidence: ConfidenceScore,
) -> str:
    warnings = "\n".join(f"- {warning}" for warning in patch.warnings) or "- none"
    evidence = "\n".join(f"- {item}" for item in analysis.evidence[:5]) or "- none"
    commands = "\n".join(f"- `{command}`" for command in validation.executed_commands[:5]) or "- none"
    return "\n".join(
        [
            "## AI Repair Summary",
            patch.summary,
            "",
            "## Root Cause",
            analysis.likely_root_cause,
            "",
            "## Evidence",
            evidence,
            "",
            "## Validation",
            f"- status: `{validation.status}`",
            f"- reproducible: `{validation.reproducible}`",
            f"- failure observed before patch: `{validation.failure_observed}`",
            f"- flaky: `{validation.flaky}`",
            commands,
            "",
            "## Safety",
            f"- changed files: `{len(patch.changed_files)}`",
            f"- changed lines: `{patch.changed_lines}`",
            f"- confidence: `{confidence.overall}`",
            f"- generation source: `{patch.generation_source}`",
            warnings,
            "",
            f"Triggered from workflow run `{failure.workflow_run_id}` on `{failure.branch}`.",
        ]
    )

def ensure_unique_branch_name(
    *,
    client: httpx.Client,
    owner: str,
    repo: str,
    desired_branch_name: str,
) -> str:
    for index in range(0, 10):
        candidate = desired_branch_name if index == 0 else f"{desired_branch_name}-{index + 1}"
        response = github_request(
            client,
            "GET",
            f"/repos/{owner}/{repo}/git/ref/heads/{candidate}",
            raise_on_status=False,
        )
        if response.status_code == 404:
            return candidate
        if response.is_error:
            response.raise_for_status()
    raise httpx.HTTPStatusError(
        "Unable to allocate a unique branch name after repeated collisions.",
        request=httpx.Request("GET", f"/repos/{owner}/{repo}/git/ref/heads/{desired_branch_name}"),
        response=httpx.Response(409),
    )


def create_commit_for_patch(
    client: httpx.Client,
    owner: str,
    repo: str,
    base_sha: str,
    branch_name: str,
    patch: PatchCandidate,
    message: str,
) -> str:
    base_commit = github_request(client, "GET", f"/repos/{owner}/{repo}/git/commits/{base_sha}")
    base_commit.raise_for_status()
    base_tree_sha = base_commit.json()["tree"]["sha"]

    tree_entries = []
    for path, content in patch.proposed_file_contents.items():
        tree_entries.append(
            {
                "path": path,
                "mode": "100644",
                "type": "blob",
                "content": content,
            }
        )

    tree_response = github_request(
        client,
        "POST",
        f"/repos/{owner}/{repo}/git/trees",
        json={"base_tree": base_tree_sha, "tree": tree_entries},
    )
    tree_response.raise_for_status()
    tree_sha = tree_response.json()["sha"]

    commit_response = github_request(
        client,
        "POST",
        f"/repos/{owner}/{repo}/git/commits",
        json={"message": message, "tree": tree_sha, "parents": [base_sha]},
    )
    commit_response.raise_for_status()
    commit_sha = commit_response.json()["sha"]

    ref_response = github_request(
        client,
        "POST",
        f"/repos/{owner}/{repo}/git/refs",
        json={"ref": f"refs/heads/{branch_name}", "sha": commit_sha},
    )
    ref_response.raise_for_status()
    return commit_sha


def create_pull_request_sync(
    client: httpx.Client,
    owner: str,
    repo: str,
    title: str,
    body: str,
    head: str,
    base: str,
    draft: bool,
) -> dict[str, Any]:
    response = github_request(
        client,
        "POST",
        f"/repos/{owner}/{repo}/pulls",
        json={
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        },
    )
    response.raise_for_status()
    return response.json()


def github_request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    raise_on_status: bool = True,
    **kwargs: Any,
) -> httpx.Response:
    attempts = max(1, settings.github_writeback_max_retries)
    last_response: httpx.Response | None = None

    for attempt in range(1, attempts + 1):
        response = client.request(method, url, **kwargs)
        last_response = response
        if response.status_code not in RETRYABLE_STATUS_CODES:
            if raise_on_status:
                response.raise_for_status()
            return response
        if attempt == attempts:
            break

        retry_after = response.headers.get("retry-after")
        wait_seconds = float(retry_after) if retry_after and retry_after.isdigit() else min(attempt, 3)
        time.sleep(wait_seconds)

    assert last_response is not None
    if raise_on_status:
        last_response.raise_for_status()
    return last_response
