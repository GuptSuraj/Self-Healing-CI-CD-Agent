from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from self_healing_agent.config import settings
from self_healing_agent.domain.models import (
    FailureAnalysis,
    FailureCategory,
    PatchCandidate,
    ValidationResult,
    WorkflowFailure,
)
from self_healing_agent.services.github import (
    get_installation_token_for_repository_sync,
    parse_full_name,
)


@dataclass
class ValidationPlan:
    repo_path: str | None
    pre_patch_commands: list[str]
    post_patch_commands: list[str]
    summary: str
    runnable: bool
    reasons: list[str]
    artifacts: list[str]


def validate_patch(
    failure: WorkflowFailure,
    analysis: FailureAnalysis,
    category: FailureCategory,
    patch: PatchCandidate,
) -> ValidationResult:
    plan = build_validation_plan(failure, analysis, category, patch)
    if not plan.runnable:
        return ValidationResult(
            status="inconclusive",
            passed=False,
            reproducible=False,
            failure_observed=False,
            flaky=False,
            executed_commands=[*plan.pre_patch_commands, *plan.post_patch_commands],
            logs="\n".join(plan.reasons),
            artifacts=plan.artifacts,
            summary=plan.summary,
        )

    if not settings.enable_validation_execution:
        return ValidationResult(
            status="planned",
            passed=False,
            reproducible=False,
            failure_observed=False,
            flaky=False,
            executed_commands=[*plan.pre_patch_commands, *plan.post_patch_commands],
            logs=(
                "Validation plan generated successfully, but execution is disabled. "
                "Set SHCA_ENABLE_VALIDATION_EXECUTION=true to run sandbox validation."
            ),
            artifacts=plan.artifacts,
            summary=plan.summary,
        )

    if shutil.which("docker") is None:
        return ValidationResult(
            status="inconclusive",
            passed=False,
            reproducible=False,
            failure_observed=False,
            flaky=False,
            executed_commands=[*plan.pre_patch_commands, *plan.post_patch_commands],
            logs="Docker is not available on the host, so validation could not execute.",
            artifacts=plan.artifacts,
            summary=plan.summary,
        )

    return execute_validation_plan(plan, patch)


def build_validation_plan(
    failure: WorkflowFailure,
    analysis: FailureAnalysis,
    category: FailureCategory,
    patch: PatchCandidate,
) -> ValidationPlan:
    context = failure.context or {}
    repo_path, repo_resolution_reasons = resolve_repo_path_for_validation(failure)
    workflow_path = analysis.bounded_context.get("workflow_path")
    changed_files = analysis.bounded_context.get("changed_files") or patch.changed_files

    reasons: list[str] = list(repo_resolution_reasons)
    artifacts: list[str] = ["validation.log", "validation.patch"]
    pre_patch_commands: list[str] = []
    post_patch_commands: list[str] = []

    pre_patch_commands = build_targeted_commands(
        repo_path=repo_path or "/workspace",
        category=category,
        workflow_path=workflow_path,
        changed_files=changed_files,
        failure=failure,
        phase="pre",
    )
    post_patch_commands = build_targeted_commands(
        repo_path=repo_path or "/workspace",
        category=category,
        workflow_path=workflow_path,
        changed_files=changed_files,
        failure=failure,
        phase="post",
    )

    if not patch.diff.strip():
        reasons.append("Patch candidate has no diff to validate.")

    summary = build_validation_summary(category, patch)
    runnable = len(reasons) == 0 and len(post_patch_commands) > 0
    return ValidationPlan(
        repo_path=repo_path,
        pre_patch_commands=pre_patch_commands,
        post_patch_commands=post_patch_commands,
        summary=summary,
        runnable=runnable,
        reasons=reasons or ["Validation plan is runnable."],
        artifacts=artifacts,
    )


def resolve_repo_path_for_validation(failure: WorkflowFailure) -> tuple[str | None, list[str]]:
    context = failure.context or {}
    repo_path = context.get("local_repo_path")
    if repo_path:
        repo = Path(repo_path)
        if not repo.exists():
            return None, [f"Attached local repository path does not exist: {repo_path}"]
        if not (repo / ".git").exists():
            return None, [f"Attached local repository path is not a git checkout: {repo_path}"]
        return str(repo), []

    if not settings.enable_validation_repo_sync:
        return None, [
            "No local repository checkout path is attached to the run; Docker validation "
            "cannot execute without a workspace to mount.",
        ]

    if shutil.which("git") is None:
        return None, ["Git is not available on the host, so repository sync cannot run."]

    try:
        return sync_repository_checkout(failure), []
    except Exception as error:
        return None, [f"Repository sync failed before validation: {error}"]


def sync_repository_checkout(failure: WorkflowFailure) -> str:
    owner, repo = parse_full_name(failure.repository)
    checkout_root = Path(settings.validation_checkout_root)
    checkout_root.mkdir(parents=True, exist_ok=True)
    target = checkout_root / f"{owner}__{repo}"

    installation_id, token = get_installation_token_for_repository_sync(
        failure.repository,
        failure.context.get("installation_id"),
    )
    if not installation_id or not token:
        raise RuntimeError("GitHub App installation token is unavailable for validation checkout.")

    remote_url = f"{settings.github_web_url.rstrip('/')}/{owner}/{repo}.git"
    git_config = ["-c", f"http.extraheader=AUTHORIZATION: Bearer {token}"]
    git_env = {"GIT_TERMINAL_PROMPT": "0"}

    if not (target / ".git").exists():
        run_git_command(
            [*git_config, "clone", "--depth", "1", remote_url, str(target)],
            env=git_env,
            cwd=checkout_root,
        )

    ref = failure.sha or failure.branch
    if not ref:
        raise RuntimeError("Neither SHA nor branch is available for validation checkout.")

    run_git_command([*git_config, "fetch", "--depth", "1", "origin", ref], env=git_env, cwd=target)
    checkout_target = failure.sha or "FETCH_HEAD"
    run_git_command(["checkout", "--force", checkout_target], env=git_env, cwd=target)
    return str(target.resolve())


def run_git_command(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path,
) -> None:
    full_env = None
    if env:
        full_env = {**os.environ, **env}
    completed = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=settings.validation_timeout_seconds,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise RuntimeError(stderr)


def build_targeted_commands(
    repo_path: str,
    category: FailureCategory,
    workflow_path: str | None,
    changed_files: list[str],
    failure: WorkflowFailure,
    phase: str,
) -> list[str]:
    if category == FailureCategory.WORKFLOW:
        workflow_target = workflow_path or ".github/workflows/unknown.yml"
        return [
            container_command(
                repo_path,
                "python -c "
                + shell_quote(
                    "from pathlib import Path; import sys, yaml; "
                    "yaml.safe_load(Path(sys.argv[1]).read_text())"
                )
                + " "
                + shell_quote(workflow_target),
            )
        ]

    if category == FailureCategory.LINT:
        return [derive_lint_command(repo_path, changed_files)]

    if category in {FailureCategory.IMPORT, FailureCategory.DEPENDENCY}:
        commands: list[str] = []
        if has_file(repo_path, "requirements.txt"):
            commands.append(container_command(repo_path, "python -m pip install -r requirements.txt"))
        elif has_file(repo_path, "package.json"):
            commands.append(container_command(repo_path, "npm install --ignore-scripts"))
        commands.append(derive_test_or_import_command(repo_path, changed_files, failure, phase))
        return commands

    if category == FailureCategory.TEST:
        return [derive_test_or_import_command(repo_path, changed_files, failure, phase)]

    return []


def has_file(repo_path: str, relative_path: str) -> bool:
    repo = Path(repo_path)
    return repo.exists() and (repo / relative_path).exists()


def derive_lint_command(repo_path: str, changed_files: list[str]) -> str:
    python_files = [path for path in changed_files if path.endswith(".py")]
    if python_files:
        joined = " ".join(shell_quote(path) for path in python_files[:10])
        return container_command(repo_path, f"ruff check {joined}")

    js_files = [path for path in changed_files if path.endswith((".js", ".jsx", ".ts", ".tsx"))]
    if js_files:
        return container_command(repo_path, "npm run lint --if-present")

    return container_command(repo_path, "git diff --check")


def derive_test_or_import_command(
    repo_path: str, changed_files: list[str], failure: WorkflowFailure, phase: str
) -> str:
    python_tests = [path for path in changed_files if "test" in path and path.endswith(".py")]
    if python_tests:
        joined = " ".join(shell_quote(path) for path in python_tests[:5])
        return container_command(repo_path, f"pytest -q {joined}")

    python_files = [path for path in changed_files if path.endswith(".py")]
    if python_files:
        if phase == "pre" and "import" in failure.failed_step.lower():
            target = shell_quote(python_files[0])
            return container_command(repo_path, f"python -m py_compile {target}")
        return container_command(repo_path, "pytest -q")

    node_tests = [path for path in changed_files if "test" in path and path.endswith((".js", ".ts", ".tsx"))]
    if node_tests:
        return container_command(repo_path, "npm test -- --runInBand")

    if any(path.endswith((".js", ".ts", ".tsx")) for path in changed_files):
        return container_command(repo_path, "npm test -- --runInBand")

    if phase == "pre":
        return container_command(repo_path, "false")
    return container_command(repo_path, "true")


def build_validation_summary(category: FailureCategory, patch: PatchCandidate) -> str:
    return (
        f"Prepared {category.value} validation plan for strategy {patch.strategy} "
        f"across {len(patch.changed_files)} file(s)."
    )


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def container_command(repo_path: str, inner_command: str) -> str:
    return (
        "docker run --rm "
        f"-v {shell_quote(repo_path)}:/workspace "
        "-w /workspace "
        f"{settings.sandbox_image_name} "
        f"sh -lc {shell_quote(inner_command)}"
    )


def execute_validation_plan(plan: ValidationPlan, patch: PatchCandidate) -> ValidationResult:
    combined_logs: list[str] = []
    executed_commands: list[str] = []

    assert plan.repo_path is not None

    with tempfile.TemporaryDirectory(prefix="shca-validation-") as tempdir:
        workspace = Path(tempdir) / "workspace"
        shutil.copytree(plan.repo_path, workspace, dirs_exist_ok=True)
        patch_file = workspace / ".shca_validation.patch"
        patch_file.write_text(patch.diff, encoding="utf-8")

        setup_commands = [
            f"docker build -t {settings.sandbox_image_name} -f apps/api/Dockerfile .",
            container_command(str(workspace), "git apply --check .shca_validation.patch"),
        ]

        for command in setup_commands:
            result = run_shell_command(command)
            executed_commands.append(command)
            combined_logs.append(render_command_result(command, result))
            if result.returncode != 0:
                return ValidationResult(
                    status="failed",
                    passed=False,
                    reproducible=False,
                    failure_observed=False,
                    flaky=False,
                    executed_commands=executed_commands,
                    logs="\n\n".join(combined_logs),
                    artifacts=plan.artifacts,
                    summary=plan.summary,
                )

        pre_failures = 0
        for command in plan.pre_patch_commands:
            adjusted = command.replace(shell_quote(plan.repo_path), shell_quote(str(workspace)))
            result = run_shell_command(adjusted)
            executed_commands.append(adjusted)
            combined_logs.append(render_command_result(adjusted, result))
            if result.returncode != 0:
                pre_failures += 1

        if plan.pre_patch_commands and pre_failures == 0:
            return ValidationResult(
                status="flaky",
                passed=False,
                reproducible=False,
                failure_observed=False,
                flaky=True,
                executed_commands=executed_commands,
                logs="\n\n".join(combined_logs),
                artifacts=plan.artifacts,
                summary=(
                    f"{plan.summary} Pre-patch reproduction unexpectedly passed, so the failure "
                    "could not be reproduced reliably."
                ),
            )

        apply_command = container_command(str(workspace), "git apply .shca_validation.patch")
        apply_result = run_shell_command(apply_command)
        executed_commands.append(apply_command)
        combined_logs.append(render_command_result(apply_command, apply_result))
        if apply_result.returncode != 0:
            return ValidationResult(
                status="failed",
                passed=False,
                reproducible=pre_failures > 0,
                failure_observed=pre_failures > 0,
                flaky=False,
                executed_commands=executed_commands,
                logs="\n\n".join(combined_logs),
                artifacts=plan.artifacts,
                summary=plan.summary,
            )

        for command in plan.post_patch_commands:
            adjusted = command.replace(shell_quote(plan.repo_path), shell_quote(str(workspace)))
            result = run_shell_command(adjusted)
            executed_commands.append(adjusted)
            combined_logs.append(render_command_result(adjusted, result))
            if result.returncode != 0:
                return ValidationResult(
                    status="failed",
                    passed=False,
                    reproducible=pre_failures > 0,
                    failure_observed=pre_failures > 0,
                    flaky=False,
                    executed_commands=executed_commands,
                    logs="\n\n".join(combined_logs),
                    artifacts=plan.artifacts,
                    summary=plan.summary,
                )

    return ValidationResult(
        status="passed",
        passed=True,
        reproducible=pre_failures > 0,
        failure_observed=pre_failures > 0,
        flaky=False,
        executed_commands=executed_commands,
        logs="\n\n".join(combined_logs),
        artifacts=plan.artifacts,
        summary=plan.summary,
    )


def run_shell_command(command: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=settings.validation_timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=error.stdout or "",
            stderr=(error.stderr or "") + f"\nTimed out after {settings.validation_timeout_seconds}s",
        )


def render_command_result(command: str, result: subprocess.CompletedProcess[str]) -> str:
    return f"$ {command}\nexit_code={result.returncode}\n{result.stdout}{result.stderr}"
