"""Runtime LLM test API for the operator dashboard.

API keys supplied here are request-scoped only. They are never persisted,
logged, or copied into config files.
"""

from __future__ import annotations

import time
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, SecretStr, field_validator

from bonbon_operator_api.auth.dependencies import require_permission
from bonbon_operator_api.models.auth_models import TokenPayload
from bonbon_operator_api.models.response_models import APIResponse

llm_router = APIRouter(prefix="/llm", tags=["llm-test"])


class LLMTestRequest(BaseModel):
    provider: Literal["ollama", "openai_compatible"] = "ollama"
    prompt: str = Field(..., min_length=1, max_length=2000)
    model: str = Field(default="llama3.2:3b", min_length=1, max_length=120)
    base_url: str = Field(default="http://localhost:11434", max_length=300)
    api_key: SecretStr | None = None
    timeout_sec: float = Field(default=30.0, ge=1.0, le=120.0)

    @field_validator("base_url")
    @classmethod
    def _base_url_must_be_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return value.rstrip("/")


@llm_router.get("/providers", response_model=APIResponse)
async def list_llm_providers(
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Return dashboard-supported test providers."""
    return APIResponse.ok(
        {
            "providers": [
                {
                    "id": "ollama",
                    "label": "Local Ollama",
                    "default_base_url": "http://localhost:11434",
                    "default_model": "llama3.2:3b",
                    "api_key_required": False,
                },
                {
                    "id": "openai_compatible",
                    "label": "OpenAI-compatible HTTP API",
                    "default_base_url": "https://api.openai.com/v1",
                    "default_model": "gpt-4o-mini",
                    "api_key_required": True,
                },
            ],
            "secret_policy": "API keys are used only for one request and are not persisted.",
        }
    )


@llm_router.post("/test-query", response_model=APIResponse)
async def test_llm_query(
    request: Request,
    body: LLMTestRequest,
    current_user: TokenPayload = Depends(require_permission("diagnostics:read")),
) -> APIResponse:
    """Send a one-shot prompt to a local or OpenAI-compatible LLM provider."""
    started = time.perf_counter()
    try:
        if body.provider == "ollama":
            response_text = await _query_ollama(body)
        else:
            response_text = await _query_openai_compatible(body)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail=f"LLM provider timed out: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        detail = _safe_http_error(exc)
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM provider unavailable: {exc}") from exc

    latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
    audit_logger = getattr(request.app.state, "audit_logger", None)
    if audit_logger is not None:
        audit_logger.log(
            actor_id=current_user.sub,
            actor_name=current_user.username,
            actor_role=current_user.role,
            action="llm:test_query",
            request_data={
                "provider": body.provider,
                "model": body.model,
                "prompt_chars": len(body.prompt),
                "latency_ms": latency_ms,
            },
        )
    return APIResponse.ok(
        {
            "provider": body.provider,
            "model": body.model,
            "response_text": response_text,
            "latency_ms": latency_ms,
        }
    )


async def _query_ollama(body: LLMTestRequest) -> str:
    url = f"{body.base_url}/api/generate"
    payload = {
        "model": body.model,
        "prompt": body.prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    async with httpx.AsyncClient(timeout=body.timeout_sec) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
    data = response.json()
    text = data.get("response", "")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=502, detail="Ollama returned an empty response")
    return text.strip()


async def _query_openai_compatible(body: LLMTestRequest) -> str:
    api_key = body.api_key.get_secret_value() if body.api_key else ""
    is_local = body.base_url.startswith(("http://localhost", "http://127.0.0.1"))
    if not api_key and not is_local:
        raise HTTPException(status_code=400, detail="api_key is required for remote providers")

    url = f"{body.base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": body.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are BonBon, a safe service robot assistant. "
                    "Answer concisely and never claim direct actuator control."
                ),
            },
            {"role": "user", "content": body.prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
    }
    async with httpx.AsyncClient(timeout=body.timeout_sec) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
    data = response.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(
            status_code=502, detail="Provider returned an unsupported response shape"
        ) from exc
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=502, detail="Provider returned an empty response")
    return text.strip()


def _safe_http_error(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    try:
        data = exc.response.json()
    except ValueError:
        return f"LLM provider returned HTTP {status}"
    message = data.get("error", data)
    if isinstance(message, dict):
        message = message.get("message", f"HTTP {status}")
    return f"LLM provider returned HTTP {status}: {message}"
