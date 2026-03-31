from __future__ import annotations

import unittest
from unittest.mock import patch

from self_healing_agent.domain.models import FailureAnalysis, FailureCategory, RepairPolicy, WorkflowFailure
from self_healing_agent.services.patcher import generate_patch


def build_failure(*, log_excerpt: str, context: dict | None = None) -> WorkflowFailure:
    return WorkflowFailure(
        repository="acme/example",
        workflow_run_id=1,
        workflow_name="ci",
        sha="abc1234",
        branch="main",
        failed_job="test",
        failed_step="step failed",
        log_excerpt=log_excerpt,
        context=context or {},
    )


def build_analysis(*, context: dict | None = None, summary: str = "summary") -> FailureAnalysis:
    return FailureAnalysis(
        fingerprint="fp-1",
        summary=summary,
        category_signals=[],
        likely_root_cause="root cause",
        evidence=[],
        bounded_context=context or {},
    )


class PatcherTests(unittest.TestCase):
    def test_generates_requirements_patch_for_missing_python_module(self) -> None:
        failure = build_failure(
            log_excerpt='ModuleNotFoundError: No module named "requests"',
        )
        analysis = build_analysis(
            context={
                "changed_file_snippets": [
                    {"path": "requirements.txt", "snippet": "fastapi\npydantic\n"}
                ]
            }
        )

        patch = generate_patch(failure, analysis, FailureCategory.DEPENDENCY, RepairPolicy())

        self.assertEqual("requirements_dependency_add", patch.strategy)
        self.assertEqual("deterministic", patch.generation_source)
        self.assertIn("requirements.txt", patch.changed_files)
        self.assertIn("requests", patch.proposed_file_contents["requirements.txt"])
        self.assertTrue(patch.safe_to_apply)

    def test_generates_package_json_patch_for_missing_node_module(self) -> None:
        failure = build_failure(
            log_excerpt='Error: Cannot find module "lodash"',
        )
        analysis = build_analysis(
            context={
                "changed_file_snippets": [
                    {
                        "path": "package.json",
                        "snippet": '{\n  "name": "web",\n  "dependencies": {\n    "react": "18.0.0"\n  }\n}\n',
                    }
                ]
            }
        )

        patch = generate_patch(failure, analysis, FailureCategory.DEPENDENCY, RepairPolicy())

        self.assertEqual("package_json_dependency_add", patch.strategy)
        self.assertIn("package.json", patch.changed_files)
        self.assertIn('"lodash": "latest"', patch.proposed_file_contents["package.json"])
        self.assertTrue(patch.safe_to_apply)

    def test_generates_test_expectation_alignment_patch(self) -> None:
        failure = build_failure(
            log_excerpt="Expected 200 but got 201",
        )
        analysis = build_analysis(
            context={
                "log_excerpt": "Expected 200 but got 201",
                "changed_file_snippets": [
                    {
                        "path": "tests/test_api.py",
                        "snippet": "def test_status():\n    assert status_code == 200\n",
                    }
                ],
            }
        )

        patch = generate_patch(failure, analysis, FailureCategory.TEST, RepairPolicy())

        self.assertEqual("test_expectation_alignment", patch.strategy)
        self.assertIn("201", patch.proposed_file_contents["tests/test_api.py"])
        self.assertTrue(patch.safe_to_apply)

    def test_blocks_oversized_llm_patch_via_policy(self) -> None:
        large_content = "\n".join(f"line {index}" for index in range(120)) + "\n"
        failure = build_failure(
            log_excerpt="unsupported issue",
            context={
                "llm_patch_response": {
                    "summary": "Large patch",
                    "rationale": "Generated externally",
                    "strategy": "llm_large_patch",
                    "proposed_file_contents": {
                        "app.py": large_content,
                    },
                }
            },
        )
        analysis = build_analysis(
            context={
                "llm_patch_response": failure.context["llm_patch_response"],
                "changed_file_snippets": [{"path": "app.py", "snippet": ""}],
            }
        )
        policy = RepairPolicy(max_changed_files=1, max_changed_lines=10)

        from self_healing_agent.config import settings

        original_flag = settings.enable_llm_patch_generation
        settings.enable_llm_patch_generation = True
        try:
            patch = generate_patch(failure, analysis, FailureCategory.UNSUPPORTED, policy)
        finally:
            settings.enable_llm_patch_generation = original_flag

        self.assertEqual("llm", patch.generation_source)
        self.assertFalse(patch.safe_to_apply)
        self.assertTrue(any("line limit" in warning.lower() for warning in patch.warnings))

    def test_uses_live_llm_provider_when_enabled(self) -> None:
        failure = build_failure(log_excerpt="ImportError: cannot import name 'x'")
        analysis = build_analysis(
            context={
                "changed_file_snippets": [{"path": "app.py", "snippet": "from old import x\n"}],
            }
        )
        policy = RepairPolicy(max_changed_files=1, max_changed_lines=20)

        from self_healing_agent.config import settings

        original_flag = settings.enable_llm_patch_generation
        settings.enable_llm_patch_generation = True
        try:
            with patch("self_healing_agent.services.patcher.llm_patch_generation_available", return_value=True), patch(
                "self_healing_agent.services.patcher.request_bounded_patch",
                return_value={
                    "summary": "Fix import",
                    "rationale": "Replace stale import",
                    "strategy": "llm_import_fix",
                    "changed_files": ["app.py"],
                    "proposed_file_contents": {"app.py": "from new import x\n"},
                },
            ):
                patch_candidate = generate_patch(
                    failure,
                    analysis,
                    FailureCategory.UNSUPPORTED,
                    policy,
                )
        finally:
            settings.enable_llm_patch_generation = original_flag

        self.assertEqual("llm", patch_candidate.generation_source)
        self.assertEqual("llm_import_fix", patch_candidate.strategy)
        self.assertTrue(any("provider interface" in warning.lower() for warning in patch_candidate.warnings))


if __name__ == "__main__":
    unittest.main()
