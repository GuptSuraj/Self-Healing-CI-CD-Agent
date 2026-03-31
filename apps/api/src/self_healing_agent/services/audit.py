from __future__ import annotations

from typing import Any

from self_healing_agent.domain.models import AuditEvent, RepairRun


def add_audit_event(run: RepairRun, event: str, payload: dict[str, Any] | None = None) -> None:
    events = normalize_audit_events(run.metadata.get("audit_events", []))
    events.append(AuditEvent(event=event, payload=payload or {}))
    run.metadata["audit_events"] = [item.model_dump() for item in events]


def normalize_audit_events(events: list[Any]) -> list[AuditEvent]:
    normalized: list[AuditEvent] = []
    for event in events:
        if isinstance(event, AuditEvent):
            normalized.append(event)
        elif isinstance(event, dict):
            normalized.append(AuditEvent.model_validate(event))
        elif isinstance(event, str):
            normalized.append(AuditEvent(event=event, payload={}))
    return normalized
