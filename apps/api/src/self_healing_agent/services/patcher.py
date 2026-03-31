from __future__ import annotations

import difflib
import json
import re
from typing import Any

from self_healing_agent.config import settings
from self_healing_agent.domain.models import (
    FailureAnalysis,
    FailureCategory,
    PatchCandidate,
    RepairPolicy,
    WorkflowFailure,
)
from self_healing_agent.services.policy import evaluate_patch_safety
from self_healing_agent.services.llm import llm_patch_generation_available, request_bounded_patch


WORKFLOW_ACTION_UPGRADES = {
    "actions/checkout@v1": "actions/checkout@v4",
    "actions/checkout@v2": "actions/checkout@v4",
    "actions/checkout@v3": "actions/checkout@v4",
    "actions/setup-node@v1": "actions/setup-node@v4",
    "actions/setup-node@v2": "actions/setup-node@v4",
    "actions/setup-node@v3": "actions/setup-node@v4",
    "actions/setup-python@v1": "actions/setup-python@v5",
    "actions/setup-python@v2": "actions/setup-python@v5",
    "actions/setup-python@v3": "actions/setup-python@v5",
    "actions/cache@v1": "actions/cache@v4",
    "actions/cache@v2": "actions/cache@v4",
    "actions/cache@v3": "actions/cache@v4",
}


def generate_patch(
    failure: WorkflowFailure,
    analysis: FailureAnalysis,
    category: FailureCategory,
    policy: RepairPolicy,
) -> PatchCandidate:
    context = analysis.bounded_context
    deterministic_candidate = build_deterministic_candidate(failure, analysis, category, context)

    # Keep deterministic output when it produced an actual patch.
    if deterministic_candidate.diff.strip():
        candidate = deterministic_candidate
    elif settings.enable_llm_patch_generation:
        candidate = build_llm_candidate(failure, analysis, category, context, policy)
        if not candidate.diff.strip():
            candidate.warnings = [*deterministic_candidate.warnings, *candidate.warnings]
    else:
        candidate = deterministic_candidate

    safe, warnings = evaluate_patch_safety(candidate, policy)
    candidate.safe_to_apply = safe
    candidate.warnings = list(dict.fromkeys([*candidate.warnings, *warnings]))
    return candidate


def build_deterministic_candidate(
    failure: WorkflowFailure,
    analysis: FailureAnalysis,
    category: FailureCategory,
    context: dict[str, Any],
) -> PatchCandidate:
    if category == FailureCategory.WORKFLOW:
        return generate_workflow_patch(failure, context)
    if category in {FailureCategory.IMPORT, FailureCategory.DEPENDENCY}:
        dependency_candidate = generate_dependency_manifest_patch(failure, context)
        if dependency_candidate.diff.strip():
            return dependency_candidate
        return generate_python_import_path_patch(failure, context)
    if category == FailureCategory.LINT:
        return generate_lint_patch(failure, context)
    if category == FailureCategory.TEST:
        return generate_test_expectation_patch(failure, context)

    return unsupported_candidate(
        failure,
        f"No deterministic safe fixer is implemented yet for {category.value} failures.",
    )


def generate_workflow_patch(
    failure: WorkflowFailure, context: dict[str, Any]
) -> PatchCandidate:
    workflow_file = context.get("workflow_file") or {}
    path = workflow_file.get("path")
    original = workflow_file.get("snippet") or ""
    if not path or not original:
        return unsupported_candidate(
            failure,
            "Workflow file content was unavailable, so no bounded workflow fix could be generated.",
        )

    updated = original
    replacements: list[str] = []
    for old, new in WORKFLOW_ACTION_UPGRADES.items():
        if old in updated:
            updated = updated.replace(old, new)
            replacements.append(f"{old} -> {new}")

    if updated == original:
        install_hint = infer_missing_install_step(failure.log_excerpt)
        if install_hint and install_hint not in updated:
            updated = original.rstrip("\n") + f"\n      - run: {install_hint}\n"
            replacements.append(f"append run step: {install_hint}")

    if updated == original:
        return unsupported_candidate(
            failure,
            "No known workflow repair was found in the bounded workflow snippet.",
        )

    diff = make_unified_diff(path, original, updated)
    return PatchCandidate(
        summary=f"Apply bounded workflow repair in {path}",
        diff=diff,
        changed_files=[path],
        changed_lines=count_changed_lines(diff),
        rationale="Applied a deterministic workflow repair based on known CI failure patterns.",
        strategy="workflow_bounded_repair",
        generation_source="deterministic",
        proposed_file_contents={path: updated},
    )


def generate_dependency_manifest_patch(
    failure: WorkflowFailure,
    context: dict[str, Any],
) -> PatchCandidate:
    module_name = extract_missing_module_name(failure.log_excerpt) or extract_missing_module_name(
        context.get("log_excerpt") or ""
    )
    if not module_name:
        return unsupported_candidate(
            failure,
            "A missing module name could not be extracted from the available failure evidence.",
        )

    snippets = context.get("changed_file_snippets") or []

    requirements = next(
        (snippet for snippet in snippets if snippet.get("path", "").endswith("requirements.txt")),
        None,
    )
    if requirements:
        return append_dependency_line(
            path=requirements["path"],
            original=requirements.get("snippet") or "",
            dependency_line=module_name.replace("_", "-"),
            failure=failure,
            strategy="requirements_dependency_add",
            rationale=(
                "Added the missing module to requirements.txt because the failure log "
                "indicates an unresolved Python module."
            ),
        )

    package_json = next(
        (snippet for snippet in snippets if snippet.get("path", "").endswith("package.json")),
        None,
    )
    if package_json:
        return append_package_json_dependency(
            failure=failure,
            path=package_json["path"],
            original=package_json.get("snippet") or "",
            package_name=normalize_node_package_name(module_name),
        )

    return unsupported_candidate(
        failure,
        "No bounded dependency manifest snippet was available for a deterministic dependency fix.",
    )


def append_dependency_line(
    *,
    path: str,
    original: str,
    dependency_line: str,
    failure: WorkflowFailure,
    strategy: str,
    rationale: str,
) -> PatchCandidate:
    if re.search(rf"(?m)^{re.escape(dependency_line)}([<>=!~].*)?$", original):
        return unsupported_candidate(
            failure,
            f"The dependency {dependency_line} already appears in {path}.",
        )

    updated = original.rstrip("\n") + f"\n{dependency_line}\n"
    diff = make_unified_diff(path, original, updated)
    return PatchCandidate(
        summary=f"Add missing dependency {dependency_line} to {path}",
        diff=diff,
        changed_files=[path],
        changed_lines=count_changed_lines(diff),
        rationale=rationale,
        strategy=strategy,
        generation_source="deterministic",
        proposed_file_contents={path: updated},
    )


def append_package_json_dependency(
    *,
    failure: WorkflowFailure,
    path: str,
    original: str,
    package_name: str,
) -> PatchCandidate:
    try:
        parsed = json.loads(original)
    except json.JSONDecodeError:
        return unsupported_candidate(
            failure,
            f"{path} could not be parsed as JSON for a bounded dependency repair.",
        )

    dependencies = parsed.get("dependencies")
    if not isinstance(dependencies, dict):
        dependencies = {}
        parsed["dependencies"] = dependencies

    if package_name in dependencies:
        return unsupported_candidate(
            failure,
            f"The dependency {package_name} already appears in {path}.",
        )

    dependencies[package_name] = "latest"
    updated = json.dumps(parsed, indent=2, sort_keys=True) + "\n"
    diff = make_unified_diff(path, original, updated)
    return PatchCandidate(
        summary=f"Add missing dependency {package_name} to {path}",
        diff=diff,
        changed_files=[path],
        changed_lines=count_changed_lines(diff),
        rationale=(
            "Added a missing Node.js dependency to package.json because the failure log "
            "indicates an unresolved module."
        ),
        strategy="package_json_dependency_add",
        generation_source="deterministic",
        proposed_file_contents={path: updated},
    )


def generate_python_import_path_patch(
    failure: WorkflowFailure,
    context: dict[str, Any],
) -> PatchCandidate:
    missing_module = extract_missing_module_name(failure.log_excerpt) or ""
    snippets = context.get("changed_file_snippets") or []
    for snippet in snippets:
        path = snippet.get("path") or ""
        original = snippet.get("snippet") or ""
        if not path.endswith(".py") or not missing_module:
            continue

        from_pattern = rf"(?m)^from {re.escape(missing_module)} import "
        if re.search(from_pattern, original):
            updated = re.sub(
                from_pattern,
                f"from .{missing_module} import ",
                original,
                count=1,
            )
            if updated != original:
                diff = make_unified_diff(path, original, updated)
                return PatchCandidate(
                    summary=f"Adjust import path in {path}",
                    diff=diff,
                    changed_files=[path],
                    changed_lines=count_changed_lines(diff),
                    rationale="Adjusted a local Python import path using a bounded import repair rule.",
                    strategy="python_relative_import_fix",
                    generation_source="deterministic",
                    proposed_file_contents={path: updated},
                )

        import_pattern = rf"(?m)^import {re.escape(missing_module)}$"
        if re.search(import_pattern, original):
            updated = re.sub(
                import_pattern,
                f"from . import {missing_module}",
                original,
                count=1,
            )
            if updated != original:
                diff = make_unified_diff(path, original, updated)
                return PatchCandidate(
                    summary=f"Adjust import path in {path}",
                    diff=diff,
                    changed_files=[path],
                    changed_lines=count_changed_lines(diff),
                    rationale="Adjusted a local Python import path using a bounded import repair rule.",
                    strategy="python_relative_import_fix",
                    generation_source="deterministic",
                    proposed_file_contents={path: updated},
                )

    return unsupported_candidate(
        failure,
        "No bounded import-path repair was found in the available file snippets.",
    )


def generate_lint_patch(
    failure: WorkflowFailure, context: dict[str, Any]
) -> PatchCandidate:
    snippets = context.get("changed_file_snippets") or []
    for snippet in snippets:
        path = snippet.get("path") or ""
        original = snippet.get("snippet") or ""
        sanitized = sanitize_whitespace(original)
        if sanitized != original:
            diff = make_unified_diff(path, original, sanitized)
            return PatchCandidate(
                summary=f"Normalize whitespace in {path}",
                diff=diff,
                changed_files=[path],
                changed_lines=count_changed_lines(diff),
                rationale=(
                    "Applied a bounded whitespace-only lint fix based on the retrieved file snippet."
                ),
                strategy="lint_whitespace_normalization",
                generation_source="deterministic",
                proposed_file_contents={path: sanitized},
            )

        simplified_quotes = normalize_quotes(original)
        if simplified_quotes != original:
            diff = make_unified_diff(path, original, simplified_quotes)
            return PatchCandidate(
                summary=f"Normalize quote style in {path}",
                diff=diff,
                changed_files=[path],
                changed_lines=count_changed_lines(diff),
                rationale="Applied a bounded quote-style normalization for a likely formatter failure.",
                strategy="lint_quote_normalization",
                generation_source="deterministic",
                proposed_file_contents={path: simplified_quotes},
            )

    return unsupported_candidate(
        failure,
        "No bounded lint repair was found in the available changed-file snippets.",
    )


def generate_test_expectation_patch(
    failure: WorkflowFailure,
    context: dict[str, Any],
) -> PatchCandidate:
    expected, actual = extract_expected_actual_values(
        context.get("log_excerpt") or failure.log_excerpt
    )
    if expected is None or actual is None:
        return unsupported_candidate(
            failure,
            "Expected/actual values could not be extracted for a bounded test repair.",
        )

    snippets = context.get("changed_file_snippets") or []
    for snippet in snippets:
        path = snippet.get("path") or ""
        original = snippet.get("snippet") or ""
        if "test" not in path.lower():
            continue

        patterns = [
            rf"(?<![A-Za-z0-9_]){re.escape(expected)}(?![A-Za-z0-9_])",
            rf"['\"]{re.escape(expected)}['\"]",
        ]
        for pattern in patterns:
            updated = re.sub(pattern, lambda m: m.group(0).replace(expected, actual), original, count=1)
            if updated != original:
                diff = make_unified_diff(path, original, updated)
                return PatchCandidate(
                    summary=f"Align test expectation in {path}",
                    diff=diff,
                    changed_files=[path],
                    changed_lines=count_changed_lines(diff),
                    rationale=(
                        "Updated a bounded test expectation using expected/actual values extracted "
                        "from the failure log."
                    ),
                    strategy="test_expectation_alignment",
                    generation_source="deterministic",
                    proposed_file_contents={path: updated},
                )

    return unsupported_candidate(
        failure,
        "No bounded test expectation repair was found in the available test snippets.",
    )


def build_llm_candidate(
    failure: WorkflowFailure,
    analysis: FailureAnalysis,
    category: FailureCategory,
    context: dict[str, Any],
    policy: RepairPolicy,
) -> PatchCandidate:
    prompt_pack = build_llm_prompt_pack(failure, analysis, category, context, policy)
    response = extract_llm_patch_response(failure, context)
    used_live_provider = False
    if response is None and llm_patch_generation_available():
        response = request_bounded_patch(prompt_pack)
        used_live_provider = response is not None
    if response is None:
        return unsupported_candidate(
            failure,
            "LLM patch generation is enabled but no bounded patch response was available.",
            strategy="llm_bounded_unavailable",
            generation_source="llm",
            warnings=[
                f"Configured provider: {settings.llm_patch_provider}.",
                f"Configured model: {settings.llm_patch_model}.",
                f"Prompt pack prepared with {len(prompt_pack)} characters of context.",
            ],
        )

    candidate = parse_llm_patch_response(failure, response)
    candidate.generation_source = "llm"
    candidate.strategy = candidate.strategy or "llm_bounded_patch"
    candidate.warnings = [
        *candidate.warnings,
        (
            "Patch was generated through the bounded LLM provider interface."
            if used_live_provider
            else "Patch was generated through the bounded LLM interface."
        ),
    ]
    return candidate


def build_llm_prompt_pack(
    failure: WorkflowFailure,
    analysis: FailureAnalysis,
    category: FailureCategory,
    context: dict[str, Any],
    policy: RepairPolicy,
) -> str:
    payload = {
        "model": settings.llm_patch_model,
        "repository": failure.repository,
        "workflow_name": failure.workflow_name,
        "failed_job": failure.failed_job,
        "failed_step": failure.failed_step,
        "category": category.value,
        "summary": analysis.summary,
        "likely_root_cause": analysis.likely_root_cause,
        "evidence": analysis.evidence[:6],
        "bounded_context": context,
        "constraints": {
            "max_changed_files": policy.max_changed_files,
            "max_changed_lines": policy.max_changed_lines,
            "protected_paths": policy.protected_paths,
            "draft_pr_only": policy.draft_pr_only,
            "must_return_json": True,
        },
        "required_response_shape": {
            "summary": "string",
            "rationale": "string",
            "strategy": "string",
            "changed_files": ["path"],
            "proposed_file_contents": {"path": "full file contents"},
        },
    }
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    max_chars = settings.llm_patch_max_context_chars
    if len(serialized) <= max_chars:
        return serialized
    return serialized[: max_chars - 17] + "\n...[truncated]..."


def extract_llm_patch_response(
    failure: WorkflowFailure,
    context: dict[str, Any],
) -> dict[str, Any] | None:
    supplied = context.get("llm_patch_response") or failure.context.get("llm_patch_response")
    if isinstance(supplied, dict):
        return supplied
    return None


def parse_llm_patch_response(
    failure: WorkflowFailure,
    response: dict[str, Any],
) -> PatchCandidate:
    summary = str(response.get("summary") or "").strip()
    rationale = str(response.get("rationale") or "").strip()
    strategy = str(response.get("strategy") or "llm_bounded_patch").strip()
    proposed = response.get("proposed_file_contents") or {}
    if not isinstance(proposed, dict) or not proposed:
        return unsupported_candidate(
            failure,
            "The bounded LLM response did not include proposed file contents.",
            strategy="llm_bounded_invalid",
            generation_source="llm",
        )

    normalized: dict[str, str] = {
        str(path): str(content) for path, content in proposed.items() if str(path).strip()
    }
    changed_files = list(normalized.keys())
    diffs: list[str] = []
    total_changed_lines = 0
    for path, updated in normalized.items():
        original = find_original_content(failure.context, path)
        diff = make_unified_diff(path, original, updated)
        diffs.append(diff)
        total_changed_lines += count_changed_lines(diff)

    return PatchCandidate(
        summary=summary or f"Apply bounded LLM fix for {failure.failed_step}",
        diff="\n".join(diff for diff in diffs if diff.strip()),
        changed_files=changed_files,
        changed_lines=total_changed_lines,
        rationale=rationale or "Generated a bounded patch candidate from the LLM interface.",
        strategy=strategy,
        generation_source="llm",
        proposed_file_contents=normalized,
    )


def find_original_content(context: dict[str, Any], path: str) -> str:
    workflow_file = context.get("workflow_file") or {}
    if workflow_file.get("path") == path:
        return str(workflow_file.get("snippet") or "")
    for snippet in context.get("changed_file_snippets") or []:
        if snippet.get("path") == path:
            return str(snippet.get("snippet") or "")
    return ""


def sanitize_whitespace(text: str) -> str:
    lines = [line.rstrip() for line in text.splitlines()]
    normalized = "\n".join(lines)
    if text.endswith("\n") or text == "":
        return normalized + ("\n" if normalized or text.endswith("\n") else "")
    return normalized + "\n"


def normalize_quotes(text: str) -> str:
    updated = re.sub(r'(?m)^(\s*)print\("([^"]+)"\)$', r"\1print('\2')", text)
    updated = re.sub(r'(?m)^(\s*)console\.log\("([^"]+)"\);?$', r"\1console.log('\2');", updated)
    return updated


def infer_missing_install_step(text: str) -> str | None:
    lowered = text.lower()
    if "npm: command not found" in lowered:
        return "npm ci"
    if "poetry: command not found" in lowered:
        return "pip install poetry"
    if "no module named pytest" in lowered:
        return "pip install -r requirements.txt"
    return None


def normalize_node_package_name(module_name: str) -> str:
    normalized = module_name.split("/")[-1].replace("_", "-")
    if normalized.startswith("@"):
        return normalized
    return normalized


def extract_expected_actual_values(text: str) -> tuple[str | None, str | None]:
    patterns = [
        r"Expected[: ]+['\"]?([^'\"\n]+)['\"]?[ ,]+but got[: ]+['\"]?([^'\"\n]+)['\"]?",
        r"expected[: ]+['\"]?([^'\"\n]+)['\"]?[ ,]+received[: ]+['\"]?([^'\"\n]+)['\"]?",
        r"AssertionError: ['\"]?([^'\"\n]+)['\"]? != ['\"]?([^'\"\n]+)['\"]?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(), match.group(2).strip()
    return None, None


def extract_missing_module_name(text: str) -> str | None:
    patterns = [
        r"No module named ['\"]([A-Za-z0-9_.-]+)['\"]",
        r"ModuleNotFoundError:.*?['\"]([A-Za-z0-9_.-]+)['\"]",
        r"Cannot find module ['\"]([A-Za-z0-9_./@-]+)['\"]",
        r"ImportError:.*?['\"]([A-Za-z0-9_.-]+)['\"]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).split("/")[-1]
    return None


def make_unified_diff(path: str, original: str, updated: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            original.splitlines(),
            updated.splitlines(),
            fromfile=path,
            tofile=path,
            lineterm="",
        )
    )


def count_changed_lines(diff: str) -> int:
    return sum(
        1
        for line in diff.splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith("+++")
        and not line.startswith("---")
    )


def unsupported_candidate(
    failure: WorkflowFailure,
    reason: str,
    *,
    strategy: str = "unsupported",
    generation_source: str = "deterministic",
    warnings: list[str] | None = None,
) -> PatchCandidate:
    return PatchCandidate(
        summary=f"No safe automatic fix generated for {failure.failed_step}",
        diff="",
        changed_files=[],
        changed_lines=0,
        rationale=reason,
        strategy=strategy,
        generation_source=generation_source,
        warnings=warnings or [],
    )
