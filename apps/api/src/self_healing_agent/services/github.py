from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from io import BytesIO
from typing import Any
from zipfile import ZipFile

import httpx
import jwt
from fastapi import HTTPException, status

from self_healing_agent.config import settings
from self_healing_agent.domain.models import WorkflowFailure


def verify_github_webhook_signature(signature: str | None, body: bytes) -> None:
    if not signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing GitHub webhook signature",
        )

    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid GitHub webhook signature",
        )


def normalize_workflow_run_failure(payload: dict[str, Any]) -> WorkflowFailure | None:
    action = payload.get("action")
    workflow_run = payload.get("workflow_run") or {}
    repository = payload.get("repository") or {}

    if action != "completed":
        return None
    if workflow_run.get("conclusion") != "failure":
        return None

    context = payload.get("_shca_context") or {}
    failed_job = context.get("failed_job") or workflow_run.get("name") or "workflow_run"
    failed_step = context.get("failed_step") or workflow_run.get("display_title") or workflow_run.get("name") or "workflow failure"
    log_excerpt = build_log_excerpt(workflow_run, context)

    return WorkflowFailure(
        repository=repository.get("full_name", "unknown/unknown"),
        workflow_run_id=int(workflow_run.get("id", 0)),
        workflow_name=workflow_run.get("name", "unknown-workflow"),
        sha=workflow_run.get("head_sha", ""),
        branch=workflow_run.get("head_branch", "unknown"),
        failed_job=failed_job,
        failed_step=failed_step,
        log_excerpt=log_excerpt,
        html_url=workflow_run.get("html_url"),
        context=context,
    )


def build_log_excerpt(workflow_run: dict[str, Any], context: dict[str, Any]) -> str:
    pieces = [
        f"event={workflow_run.get('event', 'unknown')}",
        f"status={workflow_run.get('status', 'unknown')}",
        f"conclusion={workflow_run.get('conclusion', 'unknown')}",
    ]

    path = workflow_run.get("path")
    if path:
        pieces.append(f"path={path}")

    head_commit = workflow_run.get("head_commit") or {}
    message = head_commit.get("message")
    if message:
        pieces.append(f"head_commit={message.splitlines()[0]}")

    if context.get("failed_job"):
        pieces.append(f"failed_job={context['failed_job']}")
    if context.get("failed_step"):
        pieces.append(f"failed_step={context['failed_step']}")
    if context.get("workflow_path"):
        pieces.append(f"workflow_path={context['workflow_path']}")
    changed_files = context.get("changed_files") or []
    if changed_files:
        pieces.append("changed_files=" + ", ".join(changed_files[:10]))
    extracted_log_excerpt = context.get("log_excerpt")
    if extracted_log_excerpt:
        pieces.append(trim_text(extracted_log_excerpt, settings.github_log_excerpt_chars))

    return "\n".join(pieces)


def github_app_configured() -> bool:
    return bool(
        settings.github_app_id
        and settings.github_private_key
        and settings.github_app_id != "local-dev"
    )


def github_sync_client() -> httpx.Client:
    return httpx.Client(
        base_url=settings.github_api_url,
        headers={"Accept": "application/vnd.github+json"},
        timeout=settings.github_probe_timeout_seconds,
    )


def get_installation_token_for_repository_sync(
    full_name: str,
    context_installation_id: int | str | None = None,
) -> tuple[int | None, str | None]:
    if not github_app_configured():
        return None, None

    owner, repo = parse_full_name(full_name)
    with github_sync_client() as client:
        installation_id = resolve_installation_id_sync(
            client,
            owner,
            repo,
            context_installation_id,
        )
        if installation_id is None:
            return None, None
        return installation_id, fetch_installation_token_sync(client, installation_id)


def github_integration_status() -> dict[str, Any]:
    configured = github_app_configured()
    status: dict[str, Any] = {
        "configured": configured,
        "api_url": settings.github_api_url,
        "app_id": settings.github_app_id,
        "installation_id": settings.github_installation_id,
        "writeback_enabled": settings.enable_github_writeback,
    }
    if not configured:
        status["reason"] = "github_app_not_configured"
        return status

    try:
        with github_sync_client() as client:
            response = client.get(
                "/app",
                headers={"Authorization": f"Bearer {build_app_jwt()}"},
            )
            response.raise_for_status()
            payload = response.json()
            status["reachable"] = True
            status["slug"] = payload.get("slug")
            status["name"] = payload.get("name")
            status["html_url"] = payload.get("html_url")
            return status
    except httpx.HTTPError as error:
        status["reachable"] = False
        status["error"] = str(error)
        return status


def probe_github_repository(full_name: str) -> dict[str, Any]:
    owner, repo = parse_full_name(full_name)
    if not github_app_configured():
        return {
            "repository": full_name,
            "configured": False,
            "reachable": False,
            "reason": "github_app_not_configured",
        }

    with github_sync_client() as client:
        installation_id = resolve_installation_id_sync(client, owner, repo, None)
        if installation_id is None:
            return {
                "repository": full_name,
                "configured": True,
                "reachable": False,
                "reason": "installation_not_found",
            }

        token = fetch_installation_token_sync(client, installation_id)
        client.headers["Authorization"] = f"Bearer {token}"

        repository_response = client.get(f"/repos/{owner}/{repo}")
        repository_response.raise_for_status()
        repository_payload = repository_response.json()

        workflows_response = client.get(f"/repos/{owner}/{repo}/actions/workflows")
        workflows_response.raise_for_status()
        workflows = workflows_response.json().get("workflows", [])

        recent_runs_response = client.get(
            f"/repos/{owner}/{repo}/actions/runs",
            params={"per_page": 5},
        )
        recent_runs_response.raise_for_status()
        recent_runs = [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "html_url": item.get("html_url"),
            }
            for item in recent_runs_response.json().get("workflow_runs", [])
        ]

        return {
            "repository": full_name,
            "configured": True,
            "reachable": True,
            "installation_id": installation_id,
            "default_branch": repository_payload.get("default_branch"),
            "private": repository_payload.get("private"),
            "permissions": repository_payload.get("permissions") or {},
            "workflow_count": len(workflows),
            "recent_runs": recent_runs,
        }


async def enrich_workflow_run_context(payload: dict[str, Any]) -> dict[str, Any]:
    if not github_app_configured():
        return {"available": False, "reason": "github_app_not_configured"}

    try:
        repository = payload.get("repository") or {}
        full_name = repository.get("full_name", "")
        owner, repo = parse_full_name(full_name)
        workflow_run = payload.get("workflow_run") or {}
        run_id = workflow_run.get("id")
        sha = workflow_run.get("head_sha", "")
        pull_requests = workflow_run.get("pull_requests") or []

        async with httpx.AsyncClient(
            base_url=settings.github_api_url,
            headers={"Accept": "application/vnd.github+json"},
            timeout=20.0,
        ) as client:
            installation_id = await resolve_installation_id(client, owner, repo)
            if installation_id is None:
                return {"available": False, "reason": "installation_not_found"}

            token = await fetch_installation_token(client, installation_id)
            client.headers["Authorization"] = f"Bearer {token}"

            jobs = await fetch_run_jobs(client, owner, repo, run_id)
            failed_job, failed_step = extract_failed_job_and_step(jobs)
            changed_files = await fetch_changed_files(
                client=client,
                owner=owner,
                repo=repo,
                pull_requests=pull_requests,
                sha=sha,
                default_branch=(repository.get("default_branch") or "main"),
            )
            workflow_path = workflow_run.get("path")
            workflow_file = await fetch_file_content(
                client=client,
                owner=owner,
                repo=repo,
                path=workflow_path,
                ref=sha,
            )
            file_snippets = await fetch_changed_file_snippets(
                client=client,
                owner=owner,
                repo=repo,
                changed_files=changed_files,
                ref=sha,
            )
            log_excerpt = await fetch_run_log_excerpt(
                client=client,
                owner=owner,
                repo=repo,
                run_id=run_id,
            )

            return {
                "available": True,
                "installation_id": installation_id,
                "workflow_path": workflow_path,
                "workflow_file": workflow_file,
                "failed_job": failed_job,
                "failed_step": failed_step,
                "jobs": jobs,
                "changed_files": changed_files,
                "changed_file_snippets": file_snippets,
                "log_excerpt": log_excerpt,
            }
    except httpx.HTTPError as error:
        return {
            "available": False,
            "reason": "github_api_error",
            "detail": str(error),
        }
    except HTTPException as error:
        return {
            "available": False,
            "reason": "payload_error",
            "detail": error.detail,
        }


def parse_full_name(full_name: str) -> tuple[str, str]:
    if "/" not in full_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid repository full_name in GitHub payload",
        )
    owner, repo = full_name.split("/", 1)
    return owner, repo


def build_app_jwt() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "iat": int((now - timedelta(seconds=60)).timestamp()),
        "exp": int((now + timedelta(minutes=9)).timestamp()),
        "iss": settings.github_app_id,
    }
    assert settings.github_private_key is not None
    return jwt.encode(payload, settings.github_private_key, algorithm="RS256")


async def resolve_installation_id(
    client: httpx.AsyncClient, owner: str, repo: str
) -> int | None:
    if settings.github_installation_id:
        return int(settings.github_installation_id)

    response = await client.get(
        f"/repos/{owner}/{repo}/installation",
        headers={"Authorization": f"Bearer {build_app_jwt()}"},
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return int(response.json()["id"])


async def fetch_installation_token(client: httpx.AsyncClient, installation_id: int) -> str:
    response = await client.post(
        f"/app/installations/{installation_id}/access_tokens",
        headers={"Authorization": f"Bearer {build_app_jwt()}"},
    )
    response.raise_for_status()
    return response.json()["token"]


async def fetch_run_jobs(
    client: httpx.AsyncClient, owner: str, repo: str, run_id: int | None
) -> list[dict[str, Any]]:
    if run_id is None:
        return []
    response = await client.get(f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs")
    response.raise_for_status()
    jobs = response.json().get("jobs", [])
    return [
        {
            "name": job.get("name"),
            "conclusion": job.get("conclusion"),
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
            "steps": [
                {
                    "name": step.get("name"),
                    "conclusion": step.get("conclusion"),
                    "number": step.get("number"),
                }
                for step in job.get("steps", [])
            ],
        }
        for job in jobs
    ]


def extract_failed_job_and_step(jobs: list[dict[str, Any]]) -> tuple[str, str]:
    for job in jobs:
        if job.get("conclusion") != "failure":
            continue
        for step in job.get("steps", []):
            if step.get("conclusion") == "failure":
                return job.get("name") or "unknown-job", step.get("name") or "unknown-step"
        return job.get("name") or "unknown-job", "job_failed"
    return "workflow_run", "workflow_failed"


async def fetch_changed_files(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    pull_requests: list[dict[str, Any]],
    sha: str,
    default_branch: str,
) -> list[str]:
    if pull_requests:
        number = pull_requests[0].get("number")
        if number:
            response = await client.get(f"/repos/{owner}/{repo}/pulls/{number}/files")
            response.raise_for_status()
            return [item["filename"] for item in response.json()]

    if sha:
        response = await client.get(f"/repos/{owner}/{repo}/compare/{default_branch}...{sha}")
        if response.status_code < 400:
            return [item["filename"] for item in response.json().get("files", [])]

    return []


async def fetch_file_content(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    path: str | None,
    ref: str,
) -> dict[str, Any] | None:
    if not path:
        return None

    response = await client.get(
        f"/repos/{owner}/{repo}/contents/{path}",
        params={"ref": ref} if ref else None,
    )
    if response.status_code >= 400:
        return None

    payload = response.json()
    if payload.get("type") != "file":
        return None

    content = decode_github_content(payload.get("content", ""), payload.get("encoding", "base64"))
    return {
        "path": path,
        "sha": payload.get("sha"),
        "snippet": trim_text(content, settings.github_context_snippet_chars),
    }


async def fetch_changed_file_snippets(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    changed_files: list[str],
    ref: str,
) -> list[dict[str, Any]]:
    snippets: list[dict[str, Any]] = []
    for path in changed_files[: settings.github_context_file_limit]:
        file_content = await fetch_file_content(client, owner, repo, path, ref)
        if file_content is not None:
            snippets.append(file_content)
    return snippets


async def fetch_run_log_excerpt(
    client: httpx.AsyncClient,
    owner: str,
    repo: str,
    run_id: int | None,
) -> str | None:
    if run_id is None:
        return None

    response = await client.get(
        f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
        follow_redirects=True,
    )
    if response.status_code >= 400:
        return None

    content_type = response.headers.get("content-type", "")
    if "zip" not in content_type and not response.content.startswith(b"PK"):
        return trim_text(response.text, settings.github_log_excerpt_chars)

    try:
        with ZipFile(BytesIO(response.content)) as archive:
            combined_parts: list[str] = []
            total_chars = 0
            for name in archive.namelist():
                if not name.endswith(".txt"):
                    continue
                text = archive.read(name).decode("utf-8", errors="replace")
                excerpt = trim_text(text, settings.github_log_excerpt_chars)
                block = f"== {name} ==\n{excerpt}"
                combined_parts.append(block)
                total_chars += len(block)
                if total_chars >= settings.github_log_excerpt_chars:
                    break
        return trim_text("\n\n".join(combined_parts), settings.github_log_excerpt_chars)
    except Exception:
        return None


def decode_github_content(content: str, encoding: str) -> str:
    if encoding != "base64":
        return content
    decoded = base64.b64decode(content.encode("utf-8"))
    return decoded.decode("utf-8", errors="replace")


def trim_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 17] + "\n...[truncated]..."


def resolve_installation_id_sync(
    client: httpx.Client,
    owner: str,
    repo: str,
    context_installation_id: Any,
) -> int | None:
    if context_installation_id:
        return int(context_installation_id)
    if settings.github_installation_id:
        return int(settings.github_installation_id)

    response = client.get(
        f"/repos/{owner}/{repo}/installation",
        headers={"Authorization": f"Bearer {build_app_jwt()}"},
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return int(response.json()["id"])


def fetch_installation_token_sync(client: httpx.Client, installation_id: int) -> str:
    response = client.post(
        f"/app/installations/{installation_id}/access_tokens",
        headers={"Authorization": f"Bearer {build_app_jwt()}"},
    )
    response.raise_for_status()
    return response.json()["token"]
