from __future__ import annotations

from self_healing_agent.config import settings
from self_healing_agent.domain.models import (
    ConfidenceScore,
    FailureCategory,
    PatchCandidate,
    RepairDecision,
    RepairPolicy,
    ValidationResult,
    WorkflowFailure,
)


def parse_csv_setting(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def default_repair_policy() -> RepairPolicy:
    return RepairPolicy(
        allowed_repositories=parse_csv_setting(settings.allowed_repositories) or ["*"],
        blocked_categories=parse_csv_setting(settings.blocked_categories),
        allowed_patch_generation_sources=parse_csv_setting(settings.allowed_patch_generation_sources)
        or ["deterministic"],
        max_changed_files=settings.max_changed_files,
        max_changed_lines=settings.max_changed_lines,
        protected_paths=parse_csv_setting(settings.protected_paths)
        or [".github/secrets", "infra/prod", "terraform/prod"],
        min_confidence_for_draft_pr=settings.min_confidence_for_draft_pr,
        min_confidence_for_pr=settings.min_confidence_for_pr,
        require_known_fixer_for_pr=settings.require_known_fixer_for_pr,
    )


def repository_allowed(repository: str, policy: RepairPolicy) -> bool:
    allowlist = policy.allowed_repositories
    if "*" in allowlist:
        return True
    return repository in allowlist


def category_allowed(category: FailureCategory, policy: RepairPolicy) -> bool:
    return category.value not in policy.blocked_categories


def patch_source_allowed(patch: PatchCandidate, policy: RepairPolicy) -> bool:
    return patch.generation_source in policy.allowed_patch_generation_sources


def known_fixer_available(category: FailureCategory, patch: PatchCandidate) -> bool:
    if patch.strategy != "unsupported":
        return True
    return category.value in {"lint", "dependency", "import", "workflow"}


def evaluate_repair_eligibility(
    failure: WorkflowFailure,
    category: FailureCategory,
    decision: RepairDecision,
    policy: RepairPolicy,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if decision != RepairDecision.REPAIR:
        reasons.append(f"Repair decision is {decision.value}.")
    if not repository_allowed(failure.repository, policy):
        reasons.append(f"Repository {failure.repository} is not in the allowlist.")
    if not category_allowed(category, policy):
        reasons.append(f"Category {category.value} is blocked by policy.")

    return len(reasons) == 0, reasons


def evaluate_pr_eligibility(
    *,
    category: FailureCategory,
    patch: PatchCandidate,
    validation: ValidationResult,
    confidence: ConfidenceScore,
    policy: RepairPolicy,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if not validation.passed:
        reasons.append("Validation did not pass.")
    if confidence.overall < policy.min_confidence_for_draft_pr:
        reasons.append(
            "Confidence below draft PR threshold: "
            f"{confidence.overall} < {policy.min_confidence_for_draft_pr}."
        )
    if not patch_source_allowed(patch, policy):
        reasons.append(
            f"Patch generation source {patch.generation_source} is blocked by policy."
        )
    if policy.require_known_fixer_for_pr and not known_fixer_available(category, patch):
        reasons.append("Policy requires a known fixer before PR creation.")

    return len(reasons) == 0, reasons


def evaluate_patch_safety(
    patch: PatchCandidate,
    policy: RepairPolicy,
) -> tuple[bool, list[str]]:
    warnings: list[str] = list(patch.warnings)

    if not patch.diff.strip():
        warnings.append("No code or configuration diff was generated.")

    if len(patch.changed_files) == 0:
        warnings.append("Patch does not target any file.")

    if len(patch.changed_files) > policy.max_changed_files:
        warnings.append(
            f"Patch exceeds file limit: {len(patch.changed_files)} > {policy.max_changed_files}."
        )

    if patch.changed_lines > policy.max_changed_lines:
        warnings.append(
            f"Patch exceeds line limit: {patch.changed_lines} > {policy.max_changed_lines}."
        )

    protected_matches = [
        path
        for path in patch.changed_files
        if any(path.startswith(prefix) for prefix in policy.protected_paths)
    ]
    if protected_matches:
        warnings.append(
            "Patch targets protected paths: " + ", ".join(protected_matches)
        )

    safe = not warnings
    return safe, warnings
