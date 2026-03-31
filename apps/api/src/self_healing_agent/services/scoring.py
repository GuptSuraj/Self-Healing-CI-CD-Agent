from self_healing_agent.domain.models import ConfidenceScore, PatchCandidate, ValidationResult


def score_candidate(
    patch: PatchCandidate, validation: ValidationResult
) -> ConfidenceScore:
    minimality = 1.0 if patch.changed_lines <= 20 else 0.7 if patch.changed_lines <= 80 else 0.3
    if validation.passed:
        validation_strength = 0.9
    elif validation.status == "planned":
        validation_strength = 0.45
    elif validation.status == "flaky":
        validation_strength = 0.1
    elif validation.status == "inconclusive":
        validation_strength = 0.2
    else:
        validation_strength = 0.15
    scope_risk = 0.85 if patch.safe_to_apply else 0.35
    overall = round((0.8 + minimality + validation_strength + scope_risk) / 4, 2)
    return ConfidenceScore(
        overall=overall,
        root_cause_certainty=0.8,
        patch_minimality=minimality,
        validation_strength=validation_strength,
        scope_risk=scope_risk,
        notes=[
            "Confidence scoring is currently heuristic.",
            f"Validation status for this run: {validation.status}.",
            f"Failure observed before patch application: {validation.failure_observed}.",
            "Production scoring should incorporate reproducibility and historical outcomes.",
        ],
    )
