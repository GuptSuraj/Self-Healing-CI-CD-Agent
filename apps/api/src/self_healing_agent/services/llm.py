from __future__ import annotations

import json
from typing import Any

import httpx

from self_healing_agent.config import settings


def llm_patch_generation_available() -> bool:
    provider = settings.llm_patch_provider.strip().lower()
    if provider == "openai":
        return bool(settings.openai_api_key)
    return False


def request_bounded_patch(prompt_pack: str) -> dict[str, Any] | None:
    provider = settings.llm_patch_provider.strip().lower()
    if provider != "openai" or not settings.openai_api_key:
        return None

    response_payload = request_openai_bounded_patch(prompt_pack)
    return extract_structured_output(response_payload)


def request_openai_bounded_patch(prompt_pack: str) -> dict[str, Any]:
    schema = {
        "name": "bounded_patch_candidate",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "summary": {"type": "string"},
                "rationale": {"type": "string"},
                "strategy": {"type": "string"},
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "proposed_file_contents": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": [
                "summary",
                "rationale",
                "strategy",
                "changed_files",
                "proposed_file_contents",
            ],
        },
        "strict": True,
    }

    with httpx.Client(
        base_url=settings.openai_api_base_url,
        timeout=60.0,
        headers={
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        },
    ) as client:
        response = client.post(
            "/responses",
            json={
                "model": settings.llm_patch_model,
                "input": [
                    {
                        "role": "developer",
                        "content": [
                            {
                                "type": "input_text",
                                "text": (
                                    "You generate minimal safe repository patches for CI failures. "
                                    "Respect every constraint in the prompt. Return only the "
                                    "requested structured patch object."
                                ),
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": prompt_pack}],
                    },
                ],
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": schema["name"],
                        "schema": schema["schema"],
                        "strict": True,
                    }
                },
                "temperature": settings.llm_patch_temperature,
            },
        )
        response.raise_for_status()
        return response.json()


def extract_structured_output(response_payload: dict[str, Any]) -> dict[str, Any] | None:
    output = response_payload.get("output") or []
    for item in output:
        content = item.get("content") or []
        for part in content:
            text = part.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

    output_text = response_payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        try:
            parsed = json.loads(output_text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed

    return None
