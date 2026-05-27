"""Integrated dashboard testbench API.

This router supports the local operator cockpit:

* module output snapshots for speech, vision, LLM, TTS, system, and safety
* request-scoped provider connectivity checks
* test-session recording for regression and improvement workflows

Secrets are intentionally excluded from all persisted session data.
"""

from __future__ import annotations

import json
import os
import platform
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, field_validator

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse

testbench_router = APIRouter(prefix="/testbench", tags=["testbench"])

ProviderName = Literal[
    "ollama",
    "openai_compatible",
    "deepgram",
    "elevenlabs",
    "roboflow",
]


class ClientOutputRequest(BaseModel):
    module: Literal["speech", "vision", "llm", "tts", "system", "safety"]
    status: Literal["idle", "ok", "warn", "error"] = "ok"
    payload: Dict[str, Any] = Field(default_factory=dict)


class ProviderCheckRequest(BaseModel):
    provider: ProviderName
    base_url: str = Field(default="", max_length=300)
    api_key: Optional[SecretStr] = None
    model: str = Field(default="", max_length=120)
    timeout_sec: float = Field(default=8.0, ge=1.0, le=30.0)

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return value.rstrip("/")


class StartSessionRequest(BaseModel):
    title: str = Field(default="BonBon local validation run", min_length=1, max_length=160)
    operator_notes: str = Field(default="", max_length=1000)
    scenario: str = Field(default="manual_dashboard_test", max_length=120)


class SessionEventRequest(BaseModel):
    module: Literal["speech", "vision", "llm", "tts", "system", "safety", "integration"]
    event_type: str = Field(..., min_length=1, max_length=80)
    status: Literal["pass", "fail", "warn", "info"] = "info"
    summary: str = Field(..., min_length=1, max_length=500)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    payload: Dict[str, Any] = Field(default_factory=dict)
    failure_label: str = Field(default="", max_length=120)


class _TestbenchStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._client_outputs: Dict[str, Dict[str, Any]] = {}
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._load()

    def set_client_output(self, module: str, status: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        safe_payload = _strip_secrets(payload)
        record = {
            "module": module,
            "status": status,
            "payload": safe_payload,
            "updated_at": time.time(),
        }
        self._client_outputs[module] = record
        return record

    def client_outputs(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._client_outputs)

    def start_session(self, title: str, scenario: str, notes: str, actor: TokenPayload) -> Dict[str, Any]:
        session_id = str(uuid.uuid4())
        session = {
            "session_id": session_id,
            "title": title,
            "scenario": scenario,
            "operator_notes": notes,
            "started_at": time.time(),
            "updated_at": time.time(),
            "created_by": {"sub": actor.sub, "username": actor.username, "role": actor.role},
            "events": [],
            "analysis": {},
        }
        self._sessions[session_id] = session
        self._save()
        return session

    def append_event(self, session_id: str, body: SessionEventRequest) -> Dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        event = {
            "event_id": str(uuid.uuid4()),
            "timestamp": time.time(),
            "module": body.module,
            "event_type": body.event_type,
            "status": body.status,
            "summary": body.summary,
            "metrics": _strip_secrets(body.metrics),
            "payload": _strip_secrets(body.payload),
            "failure_label": body.failure_label,
        }
        session["events"].append(event)
        session["updated_at"] = event["timestamp"]
        session["analysis"] = _analyse_session(session)
        self._save()
        return event

    def get_session(self, session_id: str) -> Dict[str, Any]:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def list_sessions(self) -> List[Dict[str, Any]]:
        return [
            {
                "session_id": item["session_id"],
                "title": item["title"],
                "scenario": item["scenario"],
                "started_at": item["started_at"],
                "updated_at": item["updated_at"],
                "event_count": len(item["events"]),
                "analysis": item.get("analysis", {}),
            }
            for item in sorted(self._sessions.values(), key=lambda row: row["updated_at"], reverse=True)
        ]

    def analyse(self, session_id: str) -> Dict[str, Any]:
        session = self.get_session(session_id)
        session["analysis"] = _analyse_session(session)
        self._save()
        return session["analysis"]

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._sessions = data.get("sessions", {})
            self._client_outputs = data.get("client_outputs", {})
        except Exception:
            self._sessions = {}
            self._client_outputs = {}

    def _save(self) -> None:
        data = {
            "sessions": self._sessions,
            "client_outputs": self._client_outputs,
        }
        self._path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def get_testbench_store(request: Request) -> _TestbenchStore:
    store = getattr(request.app.state, "testbench_store", None)
    if store is None:
        root = Path(os.getenv("BONBON_TESTBENCH_STORE", "/tmp/bonbon/operator_api/testbench_sessions.json"))
        store = _TestbenchStore(root)
        request.app.state.testbench_store = store
    return store


@testbench_router.get("/status", response_model=APIResponse)
async def get_testbench_status(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Return a merged browser + robot status snapshot for all dashboard panels."""
    store = get_testbench_store(request)
    robot = request.app.state.status_aggregator.get_status()
    client = store.client_outputs()
    return APIResponse.ok(_build_status_snapshot(robot.model_dump(), client))


@testbench_router.post("/client-output", response_model=APIResponse)
async def update_client_output(
    request: Request,
    body: ClientOutputRequest,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Record the latest browser-side output for one testbench module."""
    record = get_testbench_store(request).set_client_output(body.module, body.status, body.payload)
    return APIResponse.ok(record)


@testbench_router.get("/providers", response_model=APIResponse)
async def get_provider_catalog(
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    return APIResponse.ok({
        "providers": [
            {
                "id": "ollama",
                "label": "Local Ollama",
                "required_secret": False,
                "default_base_url": "http://127.0.0.1:11434",
                "default_model": "llama3.2:3b",
                "tests": ["models endpoint", "generation endpoint via LLM panel"],
            },
            {
                "id": "openai_compatible",
                "label": "OpenAI-compatible LLM",
                "required_secret": True,
                "default_base_url": "https://api.openai.com/v1",
                "default_model": "gpt-4o-mini",
                "tests": ["model list", "chat completions via LLM panel"],
            },
            {
                "id": "deepgram",
                "label": "Deepgram STT",
                "required_secret": True,
                "default_base_url": "https://api.deepgram.com/v1",
                "default_model": "nova-3",
                "tests": ["account/projects endpoint"],
            },
            {
                "id": "elevenlabs",
                "label": "ElevenLabs TTS",
                "required_secret": True,
                "default_base_url": "https://api.elevenlabs.io/v1",
                "default_model": "eleven_multilingual_v2",
                "tests": ["voices endpoint"],
            },
            {
                "id": "roboflow",
                "label": "Roboflow Vision",
                "required_secret": True,
                "default_base_url": "https://api.roboflow.com",
                "default_model": "workspace/project/version",
                "tests": ["account endpoint"],
            },
        ],
        "secret_policy": "Secrets are accepted per request only and never stored in sessions.",
    })


@testbench_router.post("/providers/check", response_model=APIResponse)
async def check_provider(
    body: ProviderCheckRequest,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Check connectivity to a local or cloud provider without persisting secrets."""
    started = time.perf_counter()
    result = await _check_provider(body)
    result["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
    return APIResponse.ok(result)


@testbench_router.post("/sessions", response_model=APIResponse)
async def start_session(
    request: Request,
    body: StartSessionRequest,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    session = get_testbench_store(request).start_session(
        title=body.title,
        scenario=body.scenario,
        notes=body.operator_notes,
        actor=current_user,
    )
    return APIResponse.ok(session)


@testbench_router.get("/sessions", response_model=APIResponse)
async def list_sessions(
    request: Request,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    return APIResponse.ok({"sessions": get_testbench_store(request).list_sessions()})


@testbench_router.get("/sessions/{session_id}", response_model=APIResponse)
async def get_session(
    request: Request,
    session_id: str,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    try:
        return APIResponse.ok(get_testbench_store(request).get_session(session_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown test session") from exc


@testbench_router.post("/sessions/{session_id}/events", response_model=APIResponse)
async def append_session_event(
    request: Request,
    session_id: str,
    body: SessionEventRequest,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    try:
        event = get_testbench_store(request).append_event(session_id, body)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown test session") from exc
    return APIResponse.ok(event)


@testbench_router.post("/sessions/{session_id}/analysis", response_model=APIResponse)
async def analyse_session(
    request: Request,
    session_id: str,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    try:
        analysis = get_testbench_store(request).analyse(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown test session") from exc
    return APIResponse.ok(analysis)


def _build_status_snapshot(robot: Dict[str, Any], client: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    speech = client.get("speech", {})
    vision = client.get("vision", {})
    llm = client.get("llm", {})
    tts = client.get("tts", {})
    system = client.get("system", {})
    safety = client.get("safety", {})

    return {
        "speech": {
            "status": speech.get("status", "idle"),
            "audio_heard": speech.get("payload", {}).get("audio_heard", False),
            "level_pct": speech.get("payload", {}).get("level_pct", 0),
            "transcript": speech.get("payload", {}).get("transcript", ""),
            "confidence": speech.get("payload", {}).get("confidence"),
            "latency_ms": speech.get("payload", {}).get("latency_ms"),
            "vad_state": speech.get("payload", {}).get("vad_state", "browser_meter"),
            "updated_at": speech.get("updated_at"),
        },
        "vision": {
            "status": vision.get("status", "idle"),
            "camera_active": robot.get("perception", {}).get("camera_active", False)
            or bool(vision.get("payload", {}).get("camera_active", False)),
            "objects": vision.get("payload", {}).get("objects", []),
            "fps": vision.get("payload", {}).get("fps", 0),
            "brightness": vision.get("payload", {}).get("brightness", 0),
            "contrast": vision.get("payload", {}).get("contrast", 0),
            "edge_score": vision.get("payload", {}).get("edge_score", 0),
            "motion": vision.get("payload", {}).get("motion", 0),
            "persons_detected": robot.get("perception", {}).get("persons_detected", 0),
            "obstacle_distance_m": robot.get("perception", {}).get("obstacle_distance_m"),
            "updated_at": vision.get("updated_at"),
        },
        "llm": {
            "status": llm.get("status", "idle"),
            "provider": llm.get("payload", {}).get("provider", "not_tested"),
            "model": llm.get("payload", {}).get("model", ""),
            "response_text": llm.get("payload", {}).get("response_text", ""),
            "latency_ms": llm.get("payload", {}).get("latency_ms"),
            "safety_filter": llm.get("payload", {}).get("safety_filter", "pending"),
            "grounding_score": llm.get("payload", {}).get("grounding_score"),
            "updated_at": llm.get("updated_at"),
        },
        "tts": {
            "status": tts.get("status", "idle"),
            "is_speaking": robot.get("tts", {}).get("is_speaking", False),
            "current_text": robot.get("tts", {}).get("current_text")
            or tts.get("payload", {}).get("current_text", ""),
            "queue_depth": robot.get("tts", {}).get("queue_depth", 0),
            "last_latency_ms": tts.get("payload", {}).get("latency_ms"),
            "updated_at": tts.get("updated_at"),
        },
        "system": {
            "status": system.get("status", "ok"),
            "api_runtime": "fastapi",
            "host_os": platform.platform(),
            "python": platform.python_version(),
            "process_uptime_sec": robot.get("uptime_sec", 0),
            "robot_online": robot.get("is_online", False),
            "active_task": robot.get("active_task"),
            "modules": robot.get("modules", {}),
            "browser_metrics": system.get("payload", {}),
        },
        "safety": {
            "status": safety.get("status", "idle"),
            "state": robot.get("safety", {}).get("state", "unknown"),
            "watchdog_ok": robot.get("safety", {}).get("watchdog_ok", True),
            "active_faults": robot.get("safety", {}).get("active_faults", []),
            "battery_pct": robot.get("battery", {}).get("percentage", 0),
            "motors_enabled": robot.get("actuation", {}).get("motors_enabled", False),
            "updated_at": safety.get("updated_at") or robot.get("last_updated"),
        },
    }


async def _check_provider(body: ProviderCheckRequest) -> Dict[str, Any]:
    if body.provider == "ollama":
        base_url = body.base_url or "http://127.0.0.1:11434"
        async with httpx.AsyncClient(timeout=body.timeout_sec) as client:
            response = await client.get(f"{base_url}/api/tags")
            response.raise_for_status()
        data = response.json()
        models = [item.get("name") for item in data.get("models", []) if item.get("name")]
        return {"provider": body.provider, "ok": True, "models": models[:20], "base_url": base_url}

    if body.provider == "openai_compatible":
        base_url = body.base_url or "https://api.openai.com/v1"
        headers = _bearer_headers(body.api_key)
        async with httpx.AsyncClient(timeout=body.timeout_sec) as client:
            response = await client.get(f"{base_url}/models", headers=headers)
            response.raise_for_status()
        data = response.json()
        models = [item.get("id") for item in data.get("data", []) if item.get("id")]
        return {"provider": body.provider, "ok": True, "models": models[:20], "base_url": base_url}

    if body.provider == "deepgram":
        base_url = body.base_url or "https://api.deepgram.com/v1"
        headers = _token_headers(body.api_key)
        async with httpx.AsyncClient(timeout=body.timeout_sec) as client:
            response = await client.get(f"{base_url}/projects", headers=headers)
            response.raise_for_status()
        return {"provider": body.provider, "ok": True, "base_url": base_url}

    if body.provider == "elevenlabs":
        base_url = body.base_url or "https://api.elevenlabs.io/v1"
        headers = _xi_headers(body.api_key)
        async with httpx.AsyncClient(timeout=body.timeout_sec) as client:
            response = await client.get(f"{base_url}/voices", headers=headers)
            response.raise_for_status()
        data = response.json()
        voices = [item.get("name") for item in data.get("voices", []) if item.get("name")]
        return {"provider": body.provider, "ok": True, "voices": voices[:20], "base_url": base_url}

    if body.provider == "roboflow":
        base_url = body.base_url or "https://api.roboflow.com"
        key = _secret_value(body.api_key)
        if not key:
            raise HTTPException(status_code=400, detail="api_key is required for roboflow")
        async with httpx.AsyncClient(timeout=body.timeout_sec) as client:
            response = await client.get(f"{base_url}/?api_key={key}")
            response.raise_for_status()
        return {"provider": body.provider, "ok": True, "base_url": base_url}

    raise HTTPException(status_code=400, detail="Unsupported provider")


def _bearer_headers(secret: Optional[SecretStr]) -> Dict[str, str]:
    value = _secret_value(secret)
    if not value:
        raise HTTPException(status_code=400, detail="api_key is required for this provider")
    return {"Authorization": f"Bearer {value}"}


def _token_headers(secret: Optional[SecretStr]) -> Dict[str, str]:
    value = _secret_value(secret)
    if not value:
        raise HTTPException(status_code=400, detail="api_key is required for this provider")
    return {"Authorization": f"Token {value}"}


def _xi_headers(secret: Optional[SecretStr]) -> Dict[str, str]:
    value = _secret_value(secret)
    if not value:
        raise HTTPException(status_code=400, detail="api_key is required for this provider")
    return {"xi-api-key": value}


def _secret_value(secret: Optional[SecretStr]) -> str:
    return secret.get_secret_value() if secret else ""


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in ("api_key", "secret", "token", "password", "authorization")):
                cleaned[key] = "[redacted]"
            else:
                cleaned[key] = _strip_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    return value


def _analyse_session(session: Dict[str, Any]) -> Dict[str, Any]:
    events = session.get("events", [])
    total = len(events)
    failures = [event for event in events if event.get("status") == "fail"]
    warnings = [event for event in events if event.get("status") == "warn"]
    modules = sorted({event.get("module", "unknown") for event in events})
    failure_labels = sorted({event.get("failure_label") for event in failures if event.get("failure_label")})

    recommendations = []
    if not events:
        recommendations.append("Run at least one speech, vision, LLM, TTS, safety, or integration test.")
    if failures:
        recommendations.append("Convert each failed event into a regression scenario before deploying.")
    if "speech" not in modules:
        recommendations.append("Add a speech test with noisy and clean utterances.")
    if "vision" not in modules:
        recommendations.append("Add a vision test covering low light, motion, and obstacle detection.")
    if "llm" not in modules:
        recommendations.append("Add an LLM answer-quality test with safety and grounding checks.")
    if "safety" not in modules:
        recommendations.append("Add emergency-stop and safety-state validation events.")

    regression_candidates = [
        {
            "name": f"regression_{event['module']}_{event['event_type']}",
            "module": event["module"],
            "failure_label": event.get("failure_label", ""),
            "expected": "must pass after fix",
            "source_event_id": event["event_id"],
        }
        for event in failures
    ]

    return {
        "total_events": total,
        "failures": len(failures),
        "warnings": len(warnings),
        "modules_covered": modules,
        "failure_labels": failure_labels,
        "deployment_ready": total > 0 and not failures and "safety" in modules,
        "recommendations": recommendations,
        "regression_candidates": regression_candidates,
    }
