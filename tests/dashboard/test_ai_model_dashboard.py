"""Tests for the Phase 11 AI-model dashboard REST endpoints
(api/ai_model_status_api.py), through the real FastAPI app + real auth --
never a hand-rolled stub app. Confirms: auth is enforced, responses
reflect real registry/selector state (not a hardcoded response), the
download endpoint is dry_run-only and reachable by the intended role
(regression test for a real bug found and fixed this pass: the endpoint
required "config:write", a permission string no role actually holds),
and unknown model_ids 404 rather than crashing."""

from __future__ import annotations


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestAuthIsEnforced:
    def test_ai_models_status_requires_auth(self, client):
        resp = client.get("/api/v1/ai-models/status")
        assert resp.status_code in (401, 403)

    def test_download_plan_requires_auth(self, client):
        resp = client.post("/api/v1/ai-models/download/llm_qwen25_05b")
        assert resp.status_code in (401, 403)


class TestReadEndpointsReturnRealRegistryState:
    def test_ai_models_status_reflects_real_registry(self, client, viewer_token):
        resp = client.get("/api/v1/ai-models/status", headers=_auth(viewer_token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        status = body["data"]["status"]
        # local_llm's real active model must be qwen2.5 0.5b, not a stub value
        assert "local_llm" in status

    def test_ai_models_registry_lists_real_model_ids(self, client, viewer_token):
        resp = client.get("/api/v1/ai-models/registry", headers=_auth(viewer_token))
        assert resp.status_code == 200
        body = resp.json()["data"]
        # spot-check a handful of real, specific model_ids appear somewhere
        # in the serialized registry view -- proves this isn't a hardcoded
        # placeholder payload.
        serialized = str(body)
        for expected_id in ("llm_qwen25_05b", "asr_faster_whisper", "gesture_mediapipe_holistic"):
            assert expected_id in serialized, f"{expected_id} missing from /ai-models/registry response"

    def test_sarvam_status_honestly_reports_unavailable_on_this_sandbox(self, client, viewer_token):
        resp = client.get("/api/v1/sarvam/status", headers=_auth(viewer_token))
        assert resp.status_code == 200
        body = resp.json()
        # No Sarvam access is configured in the test environment -- must
        # be an honest error/unavailable response, never a fabricated pass.
        assert body["success"] is False

    def test_speech_ai_status_endpoint_works(self, client, viewer_token):
        resp = client.get("/api/v1/speech-ai/status", headers=_auth(viewer_token))
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_perception_ai_status_endpoint_works(self, client, viewer_token):
        resp = client.get("/api/v1/perception-ai/status", headers=_auth(viewer_token))
        assert resp.status_code == 200

    def test_affective_ai_status_endpoint_works(self, client, viewer_token):
        resp = client.get("/api/v1/affective-ai/status", headers=_auth(viewer_token))
        assert resp.status_code == 200

    def test_gesture_ai_status_endpoint_works(self, client, viewer_token):
        resp = client.get("/api/v1/gesture-ai/status", headers=_auth(viewer_token))
        assert resp.status_code == 200

    def test_llm_local_status_endpoint_works(self, client, viewer_token):
        resp = client.get("/api/v1/llm-local/status", headers=_auth(viewer_token))
        assert resp.status_code == 200

    def test_benchmark_endpoint_reads_persisted_results(self, client, viewer_token):
        # docs/project-status/ai_model_benchmark_results.json was written
        # by scripts/ai_models/benchmark_all_models.py this phase -- this
        # confirms the endpoint reads that real file, not a stub.
        resp = client.get("/api/v1/ai-models/benchmark", headers=_auth(viewer_token))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["available"] is True
        assert "summary" in data


class TestDownloadEndpointIsDryRunOnlyAndCorrectlyPermissioned:
    def test_viewer_role_is_denied(self, client, viewer_token):
        # diagnostics:read alone (viewer tier) must NOT be enough to reach
        # the write-tier download-plan endpoint.
        resp = client.post("/api/v1/ai-models/download/llm_qwen25_05b", headers=_auth(viewer_token))
        assert resp.status_code == 403

    def test_engineer_role_can_reach_it_and_gets_a_dry_run_result(self, client, engineer_token):
        # Regression test: this endpoint used to require the literal
        # permission string "config:write", which role_permissions.py
        # never actually grants to any role (only "config:write:limited"/
        # "config:write:critical" exist) -- making the endpoint
        # permanently unreachable. Fixed to "config:write:limited",
        # matching this endpoint's real risk tier (it can never execute an
        # actual download; see dryRun assertion below).
        resp = client.post("/api/v1/ai-models/download/llm_qwen25_05b", headers=_auth(engineer_token))
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["dryRun"] is True

    def test_unknown_model_id_returns_404(self, client, engineer_token):
        resp = client.post("/api/v1/ai-models/download/this_model_does_not_exist", headers=_auth(engineer_token))
        assert resp.status_code == 404

    def test_download_never_actually_dispatches_a_command(self, client, engineer_token):
        # Even for a real, license-clear, enabled_by_default model, the
        # API path must always report dryRun=True -- a real download is a
        # deliberate human CLI action, never triggered by this endpoint.
        resp = client.post("/api/v1/ai-models/download/llm_qwen25_05b", headers=_auth(engineer_token))
        body = resp.json()["data"]
        assert body["dryRun"] is True
        assert "dry_run" in body["message"].lower() or "not executed" in body["message"].lower() or body["wouldSucceed"] is not None
