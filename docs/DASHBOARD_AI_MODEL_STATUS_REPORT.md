# Dashboard AI Model Status Report

Phase 11/14. Covers the 13 REST endpoints and 5 WebSocket channels that
give the operator dashboard real, live visibility into every AI model's
active backend/runtime/fallback/latency/status — rule 11 ("dashboard must
show real active model/runtime/fallback/latency/status").

## Architecture

```
config/models/model_registry.yaml (39 entries)
        │
        ▼
ModelRegistry / ModelRuntimeSelector / ModelFallbackPolicy / ModelHealthMonitor
        │
        ▼
ModelDashboardPublisher (bonbon_ai_model_registry.model_dashboard_publisher)
        │
        ├──► REST: bonbon_operator_api/api/ai_model_status_api.py (13 endpoints)
        └──► WS:   bonbon_operator_api/websocket/ai_model_snapshots.py (5 channels)
                        │
                        └── merged into the existing CHANNEL_SNAPSHOTS dict
                            (status_broadcasters.py) — extends, doesn't
                            duplicate, the pre-existing generic /ws/{channel}
                            endpoint + periodic broadcaster this repo
                            already had for boot-topology/ai-runtime/
                            pi-efficiency/validation/deployment-readiness.
```

Both the REST pull path and the WS push path call the exact same
`ai_model_snapshots.py` snapshot functions — they can never disagree,
same principle already used for `bonbon_customer_ui`'s connection-status
dashboard.

## 13 REST endpoints (all under `/api/v1`, all real-data, zero hardcoded)

| Endpoint | Permission | Purpose |
|---|---|---|
| `GET /ai-models/registry` | diagnostics:read | full registry view |
| `GET /ai-models/status` | diagnostics:read | live status per capability |
| `GET /ai-models/download-plan` | diagnostics:read | what would download, and why/why-not |
| `POST /ai-models/download/{model_id}` | config:write:limited | dry-run-only download plan (never executes) |
| `GET /ai-models/benchmark` | diagnostics:read | last persisted benchmark results |
| `GET /speech-ai/status` | diagnostics:read | ASR+TTS+VAD+wake+translation |
| `GET /speech-ai/asr` | diagnostics:read | ASR+VAD+wake only |
| `GET /speech-ai/tts` | diagnostics:read | TTS only |
| `GET /sarvam/status` | diagnostics:read | live Sarvam access detection |
| `GET /llm-local/status` | diagnostics:read | local_llm+local_rag+hospital_faq |
| `GET /perception-ai/status` | diagnostics:read | object/person/gesture/pose/face |
| `GET /affective-ai/status` | diagnostics:read | face/voice emotion+diarization |
| `GET /gesture-ai/status` | diagnostics:read | gesture+pose only |

## 5 WebSocket channels

`ai-models`, `speech-ai`, `sarvam`, `perception-ai`, `affective-ai` — all
registered in `ws_manager.VALID_CHANNELS` and
`ws_router._CHANNEL_MIN_PERMISSION` (all `diagnostics:read`), all served
by the existing generic `ws://<host>/ws/{channel}` endpoint.

## Two real bugs found and fixed this pass

1. **Unreachable download endpoint.** `POST /ai-models/download/{model_id}`
   required the literal permission string `"config:write"`. But
   `role_permissions.py` never grants that exact string to any role —
   only `"config:write:limited"` (engineer+) and `"config:write:critical"`
   (admin-only) exist. The endpoint was therefore **permanently
   unreachable by every role**, always 403. Fixed to
   `"config:write:limited"`, matching the endpoint's actual risk tier (it
   can never execute a real download — always `dry_run=True`). Caught
   while writing `tests/dashboard/test_ai_model_dashboard.py` before any
   real operator hit this dead end.
2. **`APIResponse.error(...)` doesn't exist.** Every "unavailable"/
   exception branch in `ai_model_status_api.py` (8 call sites) called a
   nonexistent classmethod — `APIResponse` only has `.ok()` and `.fail()`;
   `error` is a plain field name, and Pydantic's `__getattr__` raised
   `AttributeError` the moment any of those branches actually executed.
   This meant **`GET /sarvam/status` (and every other endpoint's
   error path) would 500-crash instead of returning a clean "unavailable"
   response** — confirmed by the `AttributeError` this session's own
   dashboard test caught live. Fixed all 8 call sites to `.fail()`.
   Regression-tested: `tests/dashboard/test_ai_model_dashboard.py::test_sarvam_status_honestly_reports_unavailable_on_this_sandbox`
   now passes and confirms a clean `success: false` response instead of a
   500.

Both bugs are the kind that only surface when the "unavailable" path is
actually exercised — exactly the path rule 1 requires this system to hit
constantly (honest unavailability, not fabricated availability), so both
were guaranteed to be hit in production. Fixing them here, before real
deployment, is the direct payoff of writing real tests against the real
app rather than only smoke-testing the "happy path."

## Verification

- `python -m py_compile` on every touched file — clean.
- Live smoke test: `build_ai_model_publisher()` → real registry load →
  real selector → real snapshots for all 5 WS channels, all returning
  `available: True` with real per-capability data (except `sarvam`,
  correctly `False` — no access configured here).
- 13 route paths enumerated directly off the live `APIRouter` object,
  matching the brief's list exactly.
- Full `tests/dashboard/` suite (15 tests) against the real FastAPI app +
  real JWT auth + real role permissions — all pass, including the two
  regression tests for the bugs above.

## Verdict: **PASS** — endpoints/channels are complete, correctly permissioned (after the fix), return real live data, and are covered by tests that exercise the real app rather than a stub.
