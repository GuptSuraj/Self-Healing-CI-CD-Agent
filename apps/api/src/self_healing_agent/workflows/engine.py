from __future__ import annotations

from typing import Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from self_healing_agent.domain.models import (
    ConfidenceScore,
    FailureAnalysis,
    FailureCategory,
    PatchCandidate,
    PullRequestInfo,
    RepairDecision,
    RepairPolicy,
    RepairRun,
    RunStatus,
    ValidationResult,
    WorkflowFailure,
)
from self_healing_agent.repositories.base import RepairRunRepository
from self_healing_agent.services.analyzer import analyze_failure
from self_healing_agent.services.audit import add_audit_event
from self_healing_agent.services.classifier import classify_failure
from self_healing_agent.services.patcher import generate_patch
from self_healing_agent.services.policy import (
    default_repair_policy,
    evaluate_pr_eligibility,
    evaluate_repair_eligibility,
)
from self_healing_agent.services.pr_writer import create_pull_request_for_fix
from self_healing_agent.services.scoring import score_candidate
from self_healing_agent.services.validator import validate_patch


class RepairWorkflowState(TypedDict, total=False):
    failure: WorkflowFailure
    run: RepairRun
    run_id: str
    analysis: FailureAnalysis
    category: FailureCategory
    decision: RepairDecision
    policy: RepairPolicy
    patch: PatchCandidate
    validation: ValidationResult
    confidence: ConfidenceScore
    pull_request: PullRequestInfo


class RepairWorkflowEngine:
    """LangGraph workflow with explicit safety gates and persistence after each stage."""

    def __init__(self, repository: RepairRunRepository) -> None:
        self.repository = repository
        self.graph = self._build_graph()

    def execute(self, failure: WorkflowFailure, run_id: str | None = None) -> RepairRun:
        initial_state: RepairWorkflowState = {
            "failure": failure,
            "run_id": run_id or str(uuid4()),
        }
        final_state = self.graph.invoke(initial_state)
        return final_state["run"]

    def _build_graph(self):
        graph = StateGraph(RepairWorkflowState)
        graph.add_node("analyze", self._analyze)
        graph.add_node("classify", self._classify)
        graph.add_node("stop_blocked", self._stop_blocked)
        graph.add_node("generate_patch", self._generate_patch)
        graph.add_node("stop_patch_blocked", self._stop_patch_blocked)
        graph.add_node("validate", self._validate)
        graph.add_node("score", self._score)
        graph.add_node("create_pr", self._create_pr)
        graph.add_node("stop_unvalidated", self._stop_unvalidated)

        graph.set_entry_point("analyze")
        graph.add_edge("analyze", "classify")
        graph.add_conditional_edges(
            "classify",
            self._route_after_classify,
            {
                "repair": "generate_patch",
                "blocked": "stop_blocked",
            },
        )
        graph.add_conditional_edges(
            "generate_patch",
            self._route_after_patch,
            {
                "validate": "validate",
                "blocked": "stop_patch_blocked",
            },
        )
        graph.add_edge("validate", "score")
        graph.add_conditional_edges(
            "score",
            self._route_after_score,
            {
                "create_pr": "create_pr",
                "stop": "stop_unvalidated",
            },
        )
        graph.add_edge("create_pr", END)
        graph.add_edge("stop_blocked", END)
        graph.add_edge("stop_patch_blocked", END)
        graph.add_edge("stop_unvalidated", END)
        return graph.compile()

    def _analyze(self, state: RepairWorkflowState) -> RepairWorkflowState:
        failure = state["failure"]
        run = self.repository.get(state["run_id"]) or RepairRun(
            run_id=state["run_id"],
            status=RunStatus.ANALYZING,
            failure=failure,
            category=FailureCategory.UNSUPPORTED,
            decision=RepairDecision.SKIP,
            metadata={},
        )
        run.status = RunStatus.ANALYZING
        analysis = analyze_failure(failure)
        policy = default_repair_policy()
        run.analysis = analysis
        run.metadata.update(
            {
                "failure_fingerprint": analysis.fingerprint,
                "root_cause_summary": analysis.likely_root_cause,
                "analysis_summary": analysis.summary,
                "category_signals": analysis.category_signals,
                "repair_policy": policy.model_dump(),
            }
        )
        add_audit_event(
            run,
            "analysis_completed",
            {
                "fingerprint": analysis.fingerprint,
                "summary": analysis.summary,
                "signals": analysis.category_signals,
            },
        )
        return {
            **state,
            "run": self.repository.upsert(run),
            "analysis": analysis,
            "policy": policy,
        }

    def _classify(self, state: RepairWorkflowState) -> RepairWorkflowState:
        failure = state["failure"]
        run = state["run"]
        analysis = state["analysis"]
        policy = state["policy"]
        category, decision = classify_failure(failure, analysis)
        run.category = category
        run.decision = decision
        allowed, reasons = evaluate_repair_eligibility(failure, category, decision, policy)
        run.metadata["repair_policy_reasons"] = reasons
        add_audit_event(
            run,
            "classified",
            {
                "category": category.value,
                "decision": decision.value,
                "policy_allowed": allowed,
                "policy_reasons": reasons,
            },
        )
        return {
            **state,
            "run": self.repository.upsert(run),
            "category": category,
            "decision": decision if allowed else RepairDecision.SKIP,
        }

    def _stop_blocked(self, state: RepairWorkflowState) -> RepairWorkflowState:
        run = state["run"]
        decision = state["decision"]
        run.status = RunStatus.FAILED
        run.metadata["time_saved_hours"] = 0.0
        add_audit_event(run, "repair_blocked", {"decision": decision.value})
        return {**state, "run": self.repository.upsert(run)}

    def _generate_patch(self, state: RepairWorkflowState) -> RepairWorkflowState:
        run = state["run"]
        failure = state["failure"]
        analysis = state["analysis"]
        category = state["category"]
        policy = state["policy"]
        patch = generate_patch(failure, analysis, category, policy)
        run.patch = patch
        run.metadata["patch_strategy"] = patch.strategy
        run.metadata["patch_generation_source"] = patch.generation_source

        if not patch.safe_to_apply:
            run.metadata["patch_warnings"] = patch.warnings
            add_audit_event(
                run,
                "patch_blocked",
                {
                    "strategy": patch.strategy,
                    "warnings": patch.warnings,
                },
            )
            return {**state, "run": self.repository.upsert(run), "patch": patch}

        run.status = RunStatus.PATCH_GENERATED
        add_audit_event(
            run,
            "patch_generated",
            {
                "strategy": patch.strategy,
                "changed_files": patch.changed_files,
                "changed_lines": patch.changed_lines,
            },
        )
        if patch.diff:
            self.repository.save_artifact(
                run.run_id,
                kind="patch_diff",
                name="patch.diff",
                content=patch.diff,
                content_type="text/x-diff",
            )
        return {**state, "run": self.repository.upsert(run), "patch": patch}

    def _stop_patch_blocked(self, state: RepairWorkflowState) -> RepairWorkflowState:
        run = state["run"]
        run.status = RunStatus.FAILED
        run.metadata["time_saved_hours"] = 0.0
        return {**state, "run": self.repository.upsert(run)}

    def _validate(self, state: RepairWorkflowState) -> RepairWorkflowState:
        run = state["run"]
        failure = state["failure"]
        analysis = state["analysis"]
        category = state["category"]
        patch = state["patch"]
        validation = validate_patch(failure, analysis, category, patch)
        run.validation = validation
        run.metadata["validation_summary"] = validation.summary
        run.metadata["validation_reproducible"] = validation.reproducible
        add_audit_event(
            run,
            "patch_validated",
            {
                "status": validation.status,
                "reproducible": validation.reproducible,
                "summary": validation.summary,
            },
        )
        if validation.logs:
            self.repository.save_artifact(
                run.run_id,
                kind="validation_log",
                name="validation.log",
                content=validation.logs,
            )
        return {**state, "run": self.repository.upsert(run), "validation": validation}

    def _score(self, state: RepairWorkflowState) -> RepairWorkflowState:
        run = state["run"]
        policy = state["policy"]
        confidence = score_candidate(state["patch"], state["validation"])
        run.confidence = confidence
        pr_allowed, reasons = evaluate_pr_eligibility(
            category=state["category"],
            patch=state["patch"],
            validation=state["validation"],
            confidence=confidence,
            policy=policy,
        )
        run.metadata["pr_policy_reasons"] = reasons
        if pr_allowed:
            run.status = RunStatus.VALIDATED
            add_audit_event(
                run,
                "validation_passed",
                {"confidence": confidence.overall, "policy_reasons": reasons},
            )
        else:
            add_audit_event(
                run,
                "repair_stopped",
                {
                    "validation_status": state["validation"].status,
                    "confidence": confidence.overall,
                    "policy_reasons": reasons,
                },
            )
        return {**state, "run": self.repository.upsert(run), "confidence": confidence}

    def _create_pr(self, state: RepairWorkflowState) -> RepairWorkflowState:
        run = state["run"]
        pull_request = create_pull_request_for_fix(
            failure=state["failure"],
            analysis=state["analysis"],
            patch=state["patch"],
            validation=state["validation"],
            confidence=state["confidence"],
        )
        run.pull_request = pull_request
        run.metadata["pull_request_status"] = pull_request.status
        if pull_request.warnings:
            run.metadata["pull_request_warnings"] = pull_request.warnings

        if pull_request.status == "created":
            run.status = RunStatus.PR_CREATED
            add_audit_event(
                run,
                "draft_pr_created",
                {
                    "branch_name": pull_request.branch_name,
                    "url": pull_request.url,
                    "number": pull_request.number,
                },
            )
        else:
            add_audit_event(
                run,
                "pr_not_created",
                {
                    "status": pull_request.status,
                    "warnings": pull_request.warnings,
                },
            )

        if pull_request.body:
            self.repository.save_artifact(
                run.run_id,
                kind="pull_request_body",
                name="pull_request.md",
                content=pull_request.body,
                content_type="text/markdown",
            )

        run.metadata["time_saved_hours"] = 0.5
        return {
            **state,
            "run": self.repository.upsert(run),
            "pull_request": pull_request,
        }

    def _stop_unvalidated(self, state: RepairWorkflowState) -> RepairWorkflowState:
        run = state["run"]
        run.status = RunStatus.FAILED
        run.metadata["time_saved_hours"] = 0.5 if run.decision == RepairDecision.REPAIR else 0.0
        return {**state, "run": self.repository.upsert(run)}

    def _route_after_classify(self, state: RepairWorkflowState) -> Literal["repair", "blocked"]:
        return "repair" if state["decision"] == RepairDecision.REPAIR else "blocked"

    def _route_after_patch(self, state: RepairWorkflowState) -> Literal["validate", "blocked"]:
        return "validate" if state["patch"].safe_to_apply else "blocked"

    def _route_after_score(self, state: RepairWorkflowState) -> Literal["create_pr", "stop"]:
        validation = state["validation"]
        confidence = state["confidence"]
        policy = state["policy"]
        patch = state["patch"]
        category = state["category"]
        allowed, _ = evaluate_pr_eligibility(
            category=category,
            patch=patch,
            validation=validation,
            confidence=confidence,
            policy=policy,
        )
        if allowed:
            return "create_pr"
        return "stop"
