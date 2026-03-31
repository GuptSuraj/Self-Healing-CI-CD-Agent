from __future__ import annotations

from uuid import uuid4

from self_healing_agent.domain.models import (
    FailureCategory,
    RepairDecision,
    RepairRun,
    RunStatus,
    WorkflowFailure,
)
from self_healing_agent.services.audit import add_audit_event


def create_detected_run(failure: WorkflowFailure) -> RepairRun:
    run = RepairRun(
        run_id=str(uuid4()),
        status=RunStatus.DETECTED,
        failure=failure,
        category=FailureCategory.UNSUPPORTED,
        decision=RepairDecision.REPAIR,
        metadata={},
    )
    add_audit_event(
        run,
        "failure_detected",
        {
            "repository": failure.repository,
            "workflow_run_id": failure.workflow_run_id,
            "failed_step": failure.failed_step,
        },
    )
    add_audit_event(run, "repair_enqueued", {})
    return run
