from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from self_healing_agent.domain.models import FailureAnalysis, FailureCategory, PatchCandidate, WorkflowFailure
from self_healing_agent.services.validator import build_validation_plan, validate_patch


def build_failure(*, context: dict | None = None) -> WorkflowFailure:
    return WorkflowFailure(
        repository="acme/example",
        workflow_run_id=7,
        workflow_name="ci",
        sha="deadbeef",
        branch="main",
        failed_job="tests",
        failed_step="import failure",
        log_excerpt='ModuleNotFoundError: No module named "requests"',
        context=context or {},
    )


def build_analysis(*, changed_files: list[str] | None = None) -> FailureAnalysis:
    return FailureAnalysis(
        fingerprint="fp-2",
        summary="dependency failure",
        category_signals=["dependency"],
        likely_root_cause="missing module",
        evidence=[],
        bounded_context={
            "changed_files": changed_files or ["requirements.txt", "tests/test_api.py"],
            "workflow_path": ".github/workflows/ci.yml",
        },
    )


def build_patch() -> PatchCandidate:
    return PatchCandidate(
        summary="Add requests",
        diff="--- requirements.txt\n+++ requirements.txt\n@@\n+requests\n",
        changed_files=["requirements.txt"],
        changed_lines=1,
        rationale="fix dependency",
        strategy="requirements_dependency_add",
        safe_to_apply=True,
        proposed_file_contents={"requirements.txt": "requests\n"},
    )


class ValidatorTests(unittest.TestCase):
    def test_build_validation_plan_marks_missing_repo_as_not_runnable(self) -> None:
        failure = build_failure()
        analysis = build_analysis()
        plan = build_validation_plan(failure, analysis, FailureCategory.DEPENDENCY, build_patch())

        self.assertFalse(plan.runnable)
        self.assertTrue(any("local repository checkout path" in reason for reason in plan.reasons))

    def test_build_validation_plan_for_git_checkout_creates_pre_and_post_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir)
            (repo / ".git").mkdir()
            (repo / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

            failure = build_failure(context={"local_repo_path": str(repo)})
            analysis = build_analysis()
            plan = build_validation_plan(
                failure,
                analysis,
                FailureCategory.DEPENDENCY,
                build_patch(),
            )

            self.assertTrue(plan.runnable)
            self.assertGreaterEqual(len(plan.pre_patch_commands), 1)
            self.assertGreaterEqual(len(plan.post_patch_commands), 1)
            self.assertTrue(any("pip install -r requirements.txt" in command for command in plan.pre_patch_commands))

    def test_validate_patch_returns_planned_when_execution_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir)
            (repo / ".git").mkdir()
            (repo / "requirements.txt").write_text("fastapi\n", encoding="utf-8")

            failure = build_failure(context={"local_repo_path": str(repo)})
            analysis = build_analysis()
            result = validate_patch(
                failure,
                analysis,
                FailureCategory.DEPENDENCY,
                build_patch(),
            )

            self.assertEqual("planned", result.status)
            self.assertFalse(result.passed)
            self.assertFalse(result.failure_observed)


if __name__ == "__main__":
    unittest.main()
