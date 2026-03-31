from __future__ import annotations

import unittest
from unittest.mock import patch

from self_healing_agent.domain.models import (
    ConfidenceScore,
    FailureAnalysis,
    FailureCategory,
    PatchCandidate,
    PullRequestInfo,
    RepairDecision,
    RunStatus,
    ValidationResult,
    WorkflowFailure,
)
from self_healing_agent.repositories.memory import InMemoryRepairRunRepository
from self_healing_agent.workflows.engine import RepairWorkflowEngine


def build_failure() -> WorkflowFailure:
    return WorkflowFailure(
        repository="acme/example",
        workflow_run_id=10,
        workflow_name="ci",
        sha="sha",
        branch="main",
        failed_job="tests",
        failed_step="lint step",
        log_excerpt="lint error",
    )


def build_analysis() -> FailureAnalysis:
    return FailureAnalysis(
        fingerprint="fp-engine",
        summary="lint failure",
        category_signals=["lint"],
        likely_root_cause="whitespace issue",
        evidence=[],
        bounded_context={},
    )


class WorkflowEngineTests(unittest.TestCase):
    def test_engine_stops_when_classification_blocks_repair(self) -> None:
        repository = InMemoryRepairRunRepository()
        engine = RepairWorkflowEngine(repository)

        with patch("self_healing_agent.workflows.engine.analyze_failure", return_value=build_analysis()), patch(
            "self_healing_agent.workflows.engine.classify_failure",
            return_value=(FailureCategory.FLAKY, RepairDecision.HUMAN_REVIEW),
        ):
            run = engine.execute(build_failure(), run_id="run-1")

        self.assertEqual(RunStatus.FAILED, run.status)
        self.assertEqual(RepairDecision.HUMAN_REVIEW, run.decision)
        self.assertIsNone(run.patch)

    def test_engine_creates_pr_path_for_validated_patch(self) -> None:
        repository = InMemoryRepairRunRepository()
        engine = RepairWorkflowEngine(repository)
        patch_candidate = PatchCandidate(
            summary="fix",
            diff="--- a\n+++ b\n@@\n+line\n",
            changed_files=["file.py"],
            changed_lines=1,
            rationale="rationale",
            strategy="deterministic",
            safe_to_apply=True,
            proposed_file_contents={"file.py": "line\n"},
        )
        validation_result = ValidationResult(
            status="passed",
            passed=True,
            reproducible=True,
            failure_observed=True,
            flaky=False,
            executed_commands=["pytest -q"],
            logs="ok",
        )
        confidence = ConfidenceScore(
            overall=0.9,
            root_cause_certainty=0.8,
            patch_minimality=1.0,
            validation_strength=0.9,
            scope_risk=0.85,
            notes=[],
        )

        with patch("self_healing_agent.workflows.engine.analyze_failure", return_value=build_analysis()), patch(
            "self_healing_agent.workflows.engine.classify_failure",
            return_value=(FailureCategory.LINT, RepairDecision.REPAIR),
        ), patch(
            "self_healing_agent.workflows.engine.generate_patch",
            return_value=patch_candidate,
        ), patch(
            "self_healing_agent.workflows.engine.validate_patch",
            return_value=validation_result,
        ), patch(
            "self_healing_agent.workflows.engine.score_candidate",
            return_value=confidence,
        ), patch(
            "self_healing_agent.workflows.engine.create_pull_request_for_fix",
            return_value=PullRequestInfo(
                status="created",
                branch_name="shca/fix",
                url="https://example/pr/1",
                number=1,
                warnings=[],
                body="body",
            ),
        ):
            run = engine.execute(build_failure(), run_id="run-2")

        self.assertEqual(RunStatus.PR_CREATED, run.status)
        self.assertEqual("created", run.pull_request.status)
        self.assertEqual("deterministic", run.metadata["patch_generation_source"])


if __name__ == "__main__":
    unittest.main()
