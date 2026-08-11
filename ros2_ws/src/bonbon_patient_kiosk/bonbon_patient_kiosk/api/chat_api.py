"""Conversational Q&A — proxies bonbon_llm's /llm/query.

PHI boundary: only the patient's free-text question is sent as query_text.
No intake/session PHI is ever placed into context_json — the hospital
directory/FAQ knowledge base (hospital_kb/) is the only thing retrievable
by bonbon_llm's RAG, exactly per the plan's stated privacy boundary.

Symptom-to-department suggestion is explicitly non-diagnostic: it maps
keywords to a department for routing convenience only, and every response
carries a disclaimer. Red-flag language short-circuits straight to the
same emergency escalation path used by intake_api.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request

from bonbon_patient_kiosk.models.chat_models import ChatQueryRequest, ChatQueryResponse
from bonbon_patient_kiosk.models.response_models import APIResponse

chat_router = APIRouter(prefix="/chat", tags=["chat"])

_EMERGENCY_PATTERN = re.compile(
    r"\b(chest\s*pain|can'?t\s*breathe|severe\s*bleeding|unconscious|stroke|"
    r"anaphylax|suicidal|overdose)\b",
    re.IGNORECASE,
)

_DEPARTMENT_KEYWORDS: dict[str, str] = {
    "dept-cardio": "heart|chest|palpitation|cardiac",
    "dept-ortho": "bone|joint|fracture|sprain|knee|shoulder|back\\s*pain",
    "dept-peds": "child|infant|baby|kid|pediatric|paediatric",
    "dept-gp": "cold|flu|fever|checkup|general",
}

_NON_DIAGNOSTIC_DISCLAIMER = (
    " This is a routing suggestion only, not a diagnosis — a doctor will "
    "assess you properly."
)


def _suggest_department(query_text: str) -> str | None:
    for dept_id, pattern in _DEPARTMENT_KEYWORDS.items():
        if re.search(pattern, query_text, re.IGNORECASE):
            return dept_id
    return None


@chat_router.post("/query", response_model=APIResponse)
async def chat_query(request: Request, body: ChatQueryRequest) -> APIResponse:
    if request.app.state.session_store.get(body.session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found or has expired")

    audit = request.app.state.audit_logger

    if _EMERGENCY_PATTERN.search(body.query_text):
        bridge = request.app.state.ros2_bridge
        bridge.publish_speak(
            "I've alerted a staff member — someone will be with you right away.",
            priority="high",
        )
        audit.log(
            actor_id=body.session_id,
            actor_role="patient",
            action="chat:emergency_escalation",
            outcome="escalated",
        )
        return APIResponse.ok(
            ChatQueryResponse(
                response_text="I've alerted a staff member immediately — please stay where you are.",
                status="escalated",
                confidence=1.0,
                is_emergency_escalation=True,
            )
        )

    bridge = request.app.state.ros2_bridge
    result = bridge.call_llm_query(
        query_text=body.query_text, speaker_id=body.session_id, require_grounding=True
    )
    suggested = _suggest_department(body.query_text)

    if result.get("success"):
        response = ChatQueryResponse(
            response_text=result.get("response_text", ""),
            status=result.get("status", "ok"),
            confidence=float(result.get("confidence", 0.0)),
            suggested_department_id=suggested,
        )
    else:
        # Graceful degradation — bonbon_llm unreachable or /llm/query not yet
        # implemented server-side (see ros2_bridge.py note). Never a 500;
        # always give the patient a next step.
        fallback = "I'm not able to look that up right now. A staff member at the desk can help."
        if suggested:
            fallback += _NON_DIAGNOSTIC_DISCLAIMER
        response = ChatQueryResponse(
            response_text=fallback,
            status="fallback",
            confidence=0.0,
            suggested_department_id=suggested,
        )

    audit.log(
        actor_id=body.session_id,
        actor_role="patient",
        action="chat:query",
        outcome=response.status,
        request_data={"chars": len(body.query_text)},
    )
    return APIResponse.ok(response)
