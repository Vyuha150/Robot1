# Three-Pi Edge AI Allocation

Edge AI Runtime brief, Phase 10. Real board allocation, mapped onto the
already-deployed three-Pi architecture (`config/distributed/*.yaml`) --
see `docs/THREE_PI_RUNTIME_AUDIT.md` for the full audit this builds on.
Machine-readable version: `config/edge_ai/three_pi_allocation.yaml`.

## Board roles

| This brief's name | Real config role | Address | Hardware |
|---|---|---|---|
| UI / Supervisor Pi | `ui_api` (`pi_ui_api.yaml`) | 192.168.10.11 | RPi5, no AI HAT, 10.1" touchscreen |
| AI Interaction Pi | `human_ai` (`pi_human_ai.yaml`) | 192.168.10.12 | RPi5 8GB + AI HAT/AI HAT+/AI HAT+2 |
| Navigation/Safety Pi | `navigation_safety` (`pi_navigation_safety.yaml`) | 192.168.10.13 | RPi5, chrony time server |

## What runs where

**UI Pi**: `bonbon_operator_dashboard`, `bonbon_dashboard_api` (Phase 12
extends this existing REST/WS surface — no new Pi-1 node). Forbidden by
config: direct motor control, camera/mic access, LLM hosting.

**AI Pi**: the full existing `bonbon_human_ai_bringup` composition
(ASR, TTS, local LLM, RAG, face recognition, multi-person tracking,
object intelligence, gesture, affective AI, human-state fusion,
speaker intelligence, behavior engine) **plus one new node this brief
adds**: `edge_ai_runtime_node` (package `bonbon_edge_ai_runtime`),
which owns the real `TaskRouter`/`SafetySeparationGuard`/`CacheManager`/
`ResourceGuard`/`InferenceScheduler` state and publishes 6 status topics
for the dashboard (`/bonbon/edge_ai/{status,models,routes,resources,safety,cache}`).
All motion output is still `/bonbon/behavior/proposal` only — see
`docs/SAFETY_SEPARATION_AUDIT.md`'s GAP-E1/E2 fixes for how that's now
actually enforced end-to-end, not just declared.

**Navigation/Safety Pi**: the full existing `bonbon_navigation_bringup`
composition (safety supervisor/gate/watchdog/estop, HAL, base
controller, actuation, motion approval gateway, Nav2). No new node —
this brief's fixes (GAP-E1/E2/E5) live inside packages this bringup
already launches.

## AI-Pi model load priority

Already exists at `config/models/pi_ai_hat_plus_2_profile.yaml`'s
`ai_pi_model_load_priority` list (wake_word → vad → asr →
person_detection → gesture_recognition → object_detection → tts →
local_rag → local_llm → face_emotion → voice_emotion →
speaker_diarization) — referenced, not duplicated, by
`config/edge_ai/three_pi_allocation.yaml`.

## Resource policy

Full condition → action → implementation table:
`config/edge_ai/resource_limits.yaml`. Summary: safety-critical modules
(ranks 1-6 in `config/pi_efficiency_profile.yaml`) are never shed;
everything else sheds under CPU/memory/thermal pressure via the existing
`LoadSheddingController`, with `bonbon_edge_ai_runtime.resource_guard`
providing a unified read-only view over that plus `Pi2LLMGuard`'s
LLM-specific disable logic.

## Launch files (this phase's addition)

- `launch/edge_ai/ui_pi_edge.launch.py` — Pi-1: includes the existing
  `bonbon_ui_api_bringup` unchanged.
- `launch/edge_ai/ai_pi_edge.launch.py` — Pi-2: includes the existing
  `bonbon_human_ai_bringup` plus the new `edge_ai_runtime_node`.
- `launch/edge_ai/nav_pi_edge.launch.py` — Pi-3: includes the existing
  `bonbon_navigation_bringup` unchanged.
- `launch/edge_ai/full_edge_sim.launch.py` — all three on one machine
  (dev/CI), forces `driver_mode:=mock`.

None of these reimplement any existing bringup — see
`docs/DUPLICATE_PIPELINE_AUDIT.md`.

## Scripts (this phase's addition)

- `scripts/edge_ai/start_ui_pi.sh` / `start_ai_pi.sh` / `start_nav_pi.sh`
  — thin `ros2 launch` wrappers around the launch files above.
- `scripts/edge_ai/check_three_pi_health.sh` — delegates to the
  existing `scripts/health_check.sh` (local module health) and
  `scripts/check_inter_pi_communication.py` (peer heartbeat/link state,
  backed by `bonbon_distributed_safety`'s real `HeartbeatMonitor`) —
  does not reimplement either.
- `scripts/edge_ai/check_edge_ai_status.sh` — genuinely new: echoes one
  message from each of `edge_ai_runtime_node`'s 6 topics with a timeout,
  never assumes the node is healthy just because the process exists.

## What this phase deliberately did NOT do

Per `docs/EDGE_AI_GAP_ANALYSIS.md` GAP-E8: `edge_ai_runtime_node` is a
status *publisher* only in this pass — it does not yet make live
routing/safety decisions for real AI-Pi requests (that requires wiring
`llm_orchestrator_node` and others to actually call into
`TaskRouter`/`SafetySeparationGuard`, a larger cross-package integration
intentionally deferred, not silently done as a side effect of adding
launch infrastructure).
