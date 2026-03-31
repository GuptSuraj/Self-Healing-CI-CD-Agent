from __future__ import annotations

import hashlib
import re
from typing import Any

from self_healing_agent.domain.models import FailureAnalysis, WorkflowFailure


ERROR_PATTERNS: list[tuple[str, str]] = [
    (r"(module not found|cannot import|importerror|modulenotfounderror)", "import"),
    (r"(eslint|ruff|prettier|lint)", "lint"),
    (r"(no matching distribution found|could not resolve dependency|dependency)", "dependency"),
    (r"(assert|expected .* but got|test failed|failed asserting)", "test"),
    (r"(\.github/workflows|yaml|workflow syntax|invalid workflow)", "workflow"),
    (r"(timed out|timeout|connection reset|network)", "flaky"),
]


def analyze_failure(failure: WorkflowFailure) -> FailureAnalysis:
    context = failure.context or {}
    raw_text = "\n".join(
        [
            failure.failed_job,
            failure.failed_step,
            failure.log_excerpt,
            str(context.get("log_excerpt") or ""),
            "\n".join(_snippet_text(context.get("changed_file_snippets") or [])),
            str((context.get("workflow_file") or {}).get("snippet") or ""),
        ]
    )
    normalized = normalize_text(raw_text)
    signals = detect_signals(normalized)
    fingerprint = build_fingerprint(failure, normalized, signals)

    changed_files = context.get("changed_files") or []
    snippets = context.get("changed_file_snippets") or []
    workflow_file = context.get("workflow_file") or {}

    evidence = [
        f"failed_job={failure.failed_job}",
        f"failed_step={failure.failed_step}",
    ]
    if changed_files:
        evidence.append("changed_files=" + ", ".join(changed_files[:5]))
    if workflow_file.get("path"):
        evidence.append(f"workflow_file={workflow_file['path']}")
    if signals:
        evidence.append("signals=" + ", ".join(signals))

    summary = build_summary(failure, signals, changed_files)
    likely_root_cause = infer_root_cause(signals, normalized, changed_files, snippets)

    bounded_context = {
        "workflow_path": context.get("workflow_path"),
        "workflow_file": workflow_file,
        "changed_files": changed_files[:10],
        "changed_file_snippets": snippets[:5],
        "job_count": len(context.get("jobs") or []),
        "log_excerpt": trim_for_context(context.get("log_excerpt") or failure.log_excerpt, 3000),
    }

    return FailureAnalysis(
        fingerprint=fingerprint,
        summary=summary,
        category_signals=signals,
        likely_root_cause=likely_root_cause,
        evidence=evidence,
        bounded_context=bounded_context,
    )


def normalize_text(value: str) -> str:
    compact = re.sub(r"\s+", " ", value.lower()).strip()
    compact = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", compact)
    compact = re.sub(r"\d+", "<n>", compact)
    return compact


def detect_signals(text: str) -> list[str]:
    signals: list[str] = []
    for pattern, label in ERROR_PATTERNS:
        if re.search(pattern, text):
            signals.append(label)
    return signals


def build_fingerprint(failure: WorkflowFailure, normalized: str, signals: list[str]) -> str:
    key = "|".join(
        [
            failure.repository,
            failure.workflow_name,
            failure.failed_job,
            failure.failed_step,
            ",".join(signals[:3]),
            normalized[:400],
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def build_summary(
    failure: WorkflowFailure, signals: list[str], changed_files: list[str]
) -> str:
    if signals:
        return (
            f"{signals[0]} failure in {failure.failed_job} / {failure.failed_step}"
            f" affecting {changed_files[0] if changed_files else failure.workflow_name}"
        )
    return f"unsupported failure in {failure.failed_job} / {failure.failed_step}"


def infer_root_cause(
    signals: list[str],
    normalized: str,
    changed_files: list[str],
    snippets: list[dict[str, Any]],
) -> str:
    if "import" in signals:
        return "A module or import path appears unresolved in the failing step."
    if "lint" in signals:
        return "A linter or formatter violation is present in recently changed code."
    if "dependency" in signals:
        return "A package dependency appears missing, unresolved, or incompatible."
    if "workflow" in signals:
        return "The workflow configuration or action invocation appears misconfigured."
    if "test" in signals:
        if changed_files:
            return f"A deterministic test assertion likely regressed after changes in {changed_files[0]}."
        return "A deterministic test assertion appears to have regressed."
    if "flaky" in signals:
        return "The failure looks environmental or flaky and should be reviewed before repair."
    if snippets and "undefined" in normalized:
        return "A changed file likely introduced a null or undefined handling issue."
    return "The failure pattern is not yet strongly classified by the current analyzer."


def _snippet_text(snippets: list[dict[str, Any]]) -> list[str]:
    return [str(snippet.get("snippet") or "") for snippet in snippets]


def trim_for_context(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 17] + "\n...[truncated]..."
