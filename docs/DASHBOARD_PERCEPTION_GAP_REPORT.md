# Dashboard Perception Gap Report

The dashboard's perception blind spot is the least ambiguous finding in
this audit: it is **simply not connected**, not partially connected.

## What exists today

- Frontend tabs labeled "Perception", "Affective AI", "Gesture", and
  "Behavior Engine" exist in `App.tsx`, but they render a **browser-side
  COCO-SSD demo** (client-side TensorFlow.js object detection running in
  the browser, unrelated to the robot) and generic testbench status
  cards — not real backend perception data.
- The ROS2 bridge (`ros2_bridge.py`) subscribes to `PersonTrack` and
  `PerceptionEfficiencyMetrics` only.
- The `bonbon_operator_api` `api/` directory has zero routers for
  objects, people, affective state, gestures, or human-state.
- `VALID_CHANNELS` (`websocket/ws_manager.py`) has 10 channels
  (`robot-status`, `safety-events`, `navigation-events`, `diagnostics`,
  `live-logs`, `boot-topology`, `ai-runtime`, `pi-efficiency`,
  `validation`, `deployment-readiness`) — none perception-specific.

## What's missing, mapped to the brief's Phase 8 requirements

| Required | Exists? |
|---|---|
| `GET /perception/objects/status`, `/classes`, `/active` | No |
| `GET /perception/people/status`, `/active` | No |
| `GET /perception/affective/status`, `/human-states` | No |
| `GET /perception/gestures/status`, `/active` | No |
| `GET /perception/human-state/active` | No |
| `GET /perception/efficiency/status` | No |
| `/ws/perception/objects`, `/people`, `/affective`, `/gestures`, `/human-state`, `/efficiency` | No |
| Object Recognition card (runtime, classes, active detections, latency, fallback) | No |
| People Tracking card (active/known/unknown counts, ID-switch warnings) | No |
| Multi-Human Emotion card (per-person state, confidences) | No |
| Gestures card (active gestures, person_track_id, safety relevance) | No |
| Human State Fusion card (active speaker/requester, recommended response) | No |
| Pi Perception Efficiency card (FPS limits, dropped frames, degraded reason) | No |

## Why this matters more than it might seem

Every failure documented in the three companion analyses (object class
coverage, voice-emotion global bug, missing gesture types) is currently
**invisible to an operator**. There is no way today to tell, from the
dashboard, whether the robot silently failed to detect a `wheelchair`
because the class isn't supported (correct, honest behavior) versus
because something crashed (a real bug) — both look identical: nothing
happened. Phase 8 closes this by making every one of these modules'
real, live state (including their honest "unavailable"/"degraded"
states) visible, following the exact "no fake PASS" pattern already
established for the boot-topology/AI-runtime/Pi-efficiency dashboard work
earlier in this project: read real data or show `available: false`,
never fabricate.

## Fix scope (Phase 8)

1. Extend the ROS2 bridge to subscribe to `HumanState`, `GestureEvent`,
   `FaceEmotion`, `VoiceEmotion`, `HumanEmotionState`, and the object
   detection/tracking topics.
2. Add the 11 REST endpoints and 6 WebSocket channels listed above,
   reusing the existing `require_permission`/`APIResponse`/`/ws/{channel}`
   patterns already proven in `deployment_api.py`/`validation_api.py`.
3. Add the 6 dashboard cards to the frontend, replacing the placeholder
   COCO-SSD demo content with real backend-sourced panels (same
   `loadX()`/`<pre className="json-view">` pattern as the existing
   "Raspberry Pi Deployment" and "Behavior Validation Framework" panels).
