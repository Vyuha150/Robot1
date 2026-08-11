# Edge AI Resource & Scheduling Report

Phase 15 summary of Phase 8's deliverable:
[`resource_guard.py`](../ros2_ws/src/bonbon_edge_ai_runtime/bonbon_edge_ai_runtime/resource_guard.py) +
[`inference_scheduler.py`](../ros2_ws/src/bonbon_edge_ai_runtime/bonbon_edge_ai_runtime/inference_scheduler.py).

## `ResourceGuard`: a facade, not a fourth resource monitor

Unifies 3 already-working, already-tested mechanisms —
`bonbon_safety.ResourceMonitor` (CPU/RAM/disk), `bonbon_perception_efficiency.LoadSheddingController`
(hysteresis-gated load level), `bonbon_llm.Pi2LLMGuard` (LLM-specific
disable decision) — into one `evaluate()` call producing a single
`ResourceGuardStatus`. None of the threshold logic is reimplemented; this
is the same documented cross-cutting-aggregation exception as
`dashboard_publisher.py`.

## `InferenceScheduler`: rule 1 enforced structurally

Reads `config/pi_efficiency_profile.yaml`'s real `priority_order`/
`queue_limits` — not a new parallel ordering. Rule 1 ("safety and
movement must never wait for AI") is enforced in code, not by
convention: `submit()` for a `safety_critical` module dispatches
**immediately**, bypassing the queue entirely — it can never be dropped
for queue-depth reasons or wait behind another module's request. Every
other module gets one bounded FIFO queue per module; when full, the
**oldest** non-critical request is dropped to make room for the newest
(a stale queued request is worth less than a fresh one once the bound is
hit). `next_ready()` also silently drops (and counts) any request that
already timed out while waiting, so a stale request is never dispatched
late.

## Verification

`tests/edge_ai/test_resource_guard.py` (4 tests) + `test_inference_scheduler.py`
(7 tests): the full `ResourceGuardStatus` field contract, thermal-overload
escalation (honestly conditioned on whether real metrics are actually
available on the running machine — a dev sandbox without real `/proc`
access correctly reports "normal" rather than fabricating an alarm from
missing data, per the underlying `LoadSheddingController`'s own "never
shed load on missing data" rule), safety-critical bypass, bounded-queue
drop-oldest behavior, and expired-task dropping.
