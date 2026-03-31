from __future__ import annotations

from typing import TypedDict

from self_healing_agent.domain.models import (
    ConfidenceScore,
    FailureCategory,
    PatchCandidate,
    RepairDecision,
    ValidationResult,
    WorkflowFailure,
)


class RepairGraphState(TypedDict, total=False):
    failure: WorkflowFailure
    category: FailureCategory
    decision: RepairDecision
    patch: PatchCandidate
    validation: ValidationResult
    confidence: ConfidenceScore
    audit_events: list[str]
