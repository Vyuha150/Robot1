# Edge AI Dashboard Integration Report

Phase 15 summary of Phase 12's deliverable: 9 dashboard cards, 13 REST
endpoints, 6 WebSocket channels — all now live in `bonbon_operator_api`.

## 9 dashboard cards

`EdgeAIDashboardPublisher`'s view methods: **Overview**, **Model
Registry**, **Speech AI**, **LLM**, **Vision AI**, **Affective AI**,
**Safety Separation**, **Resource Guard**, **Cache**. Registry/Speech/LLM/
Affective delegate wholesale to `ModelDashboardPublisher` built on the
merged registry (Phase 2/3) — the 3 new capabilities automatically get
the same status/fallback/dashboard-visibility treatment as the original
16 through this delegation, zero new view code required for them
specifically.

## 13 REST endpoints

9 genuinely new under `edge_ai_status_api.py` (`/edge-ai/status`,
`/edge-ai/model-registry`, `/edge-ai/routes`, `/edge-ai/cache`,
`/edge-ai/resource-guard`, `/edge-ai/degraded-mode`,
`/edge-ai/safety-separation`, `/edge-ai/benchmarks`, `/vision-ai/status`)
+ 4 pre-existing (`/ai-models/status`, `/speech-ai/status`,
`/llm-local/status`, `/affective-ai/status`) = 13 total, matching the
brief exactly.

## 6 WebSocket channels

`edge-ai-status`, `edge-ai-models`, `edge-ai-routes`, `edge-ai-resources`,
`edge-ai-safety`, `edge-ai-cache` — added to `VALID_CHANNELS`,
`_CHANNEL_MIN_PERMISSION` (all `diagnostics:read`), and
`CHANNEL_SNAPSHOTS` via the same snapshot-function pattern
`ai_model_snapshots.py` established.

## Stateful vs. recomputable — a deliberate distinction

Config/registry-based views (model registry, speech, LLM, affective, and
vision's model-selection half) are cheaply and honestly recomputed fresh
per HTTP request. Genuinely **stateful** views (safety-block counts,
cache hit rates, live resource readings, in-flight routing decisions) are
never reconstructed fresh — that would always show a misleadingly empty
zero-state. They relay the real, persistent `edge_ai_runtime_node`
process's state via cached ROS2 topic messages
(`ROS2DashboardBridge.get_edge_ai_snapshot()`), honestly reporting one of
3 states: no bridge, bridge-but-no-message-yet, or a real relayed
message — never fabricating the third state as the first or second.

## Verification

7 touched/new files (`ros2_bridge.py`, `edge_ai_snapshots.py`,
`edge_ai_status_api.py`, `ws_manager.py`, `ws_router.py`,
`status_broadcasters.py`, `main.py`) byte-compile cleanly; the router
registers exactly 9 new routes; snapshot functions verified to report all
3 honest states correctly via direct smoke test;
`/vision-ai/status`'s handler confirmed to return real live capability
data (e.g. `gesture_recognition` resolving to the real installed
MediaPipe backend). `bonbon_operator_api`'s full test suite: **233/233
passing** (one pre-existing stale assertion in
`test_status_broadcasters.py::test_all_channel_snapshots_registered` was
found and fixed during this verification — it was missing the AI-model
and edge_ai channels added across this and the prior AI-model-stack pass,
not a new regression from this phase's own changes).
