from self_healing_agent.domain.models import (
    FailureAnalysis,
    FailureCategory,
    RepairDecision,
    WorkflowFailure,
)


def classify_failure(
    failure: WorkflowFailure, analysis: FailureAnalysis | None = None
) -> tuple[FailureCategory, RepairDecision]:
    text = f"{failure.failed_step}\n{failure.log_excerpt}".lower()
    if analysis:
        text = f"{text}\n{' '.join(analysis.category_signals)}\n{analysis.likely_root_cause.lower()}"

    if "eslint" in text or "ruff" in text or "prettier" in text or "lint" in text:
        return FailureCategory.LINT, RepairDecision.REPAIR
    if "module not found" in text or "cannot import" in text or "importerror" in text:
        return FailureCategory.IMPORT, RepairDecision.REPAIR
    if "dependency" in text or "no matching distribution found" in text:
        return FailureCategory.DEPENDENCY, RepairDecision.REPAIR
    if "assert" in text or "expected" in text or "test failed" in text:
        return FailureCategory.TEST, RepairDecision.REPAIR
    if ".github/workflows" in text or "workflow" in text or "yaml" in text:
        return FailureCategory.WORKFLOW, RepairDecision.REPAIR
    if "flaky" in text or "timed out" in text or "network" in text:
        return FailureCategory.FLAKY, RepairDecision.HUMAN_REVIEW
    return FailureCategory.UNSUPPORTED, RepairDecision.SKIP
