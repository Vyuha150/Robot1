"""LLM test API tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_llm_providers_are_listed(client: TestClient, viewer_token: str):
    resp = client.get(
        "/api/v1/llm/providers",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert {provider["id"] for provider in data["providers"]} == {"ollama", "openai_compatible"}
    assert "not persisted" in data["secret_policy"]


def test_llm_query_uses_request_scoped_key_without_audit_leak(
    client: TestClient,
    viewer_token: str,
    audit_logger,
    monkeypatch: pytest.MonkeyPatch,
):
    from bonbon_operator_api.api import llm_test_api

    async def fake_query(_body):
        return "Hello from a test model."

    monkeypatch.setattr(llm_test_api, "_query_openai_compatible", fake_query)

    resp = client.post(
        "/api/v1/llm/test-query",
        json={
            "provider": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "prompt": "My private prompt",
            "api_key": "sk-test-secret-value",
        },
        headers={"Authorization": f"Bearer {viewer_token}"},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["response_text"] == "Hello from a test model."
    events = audit_logger.query(action="llm:test_query", limit=1)
    assert events
    serialized = str(events[0])
    assert "sk-test-secret-value" not in serialized
    assert "My private prompt" not in serialized
    assert "prompt_chars" in serialized


def test_remote_openai_compatible_requires_api_key(client: TestClient, viewer_token: str):
    resp = client.post(
        "/api/v1/llm/test-query",
        json={
            "provider": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "prompt": "hello",
        },
        headers={"Authorization": f"Bearer {viewer_token}"},
    )

    assert resp.status_code == 400
    assert "api_key is required" in resp.json()["detail"]


def test_llm_query_requires_auth(client: TestClient):
    resp = client.post(
        "/api/v1/llm/test-query",
        json={
            "provider": "ollama",
            "base_url": "http://localhost:11434",
            "model": "llama3.2:3b",
            "prompt": "hello",
        },
    )

    assert resp.status_code == 401
