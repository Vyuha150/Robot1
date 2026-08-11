# Edge AI Accelerator Manager Report

Phase 15 summary of Phase 5's deliverable:
[`accelerator_manager.py`](../ros2_ws/src/bonbon_edge_ai_runtime/bonbon_edge_ai_runtime/accelerator_manager.py).

## What's new vs. what's reused

Per [`docs/DUPLICATE_PIPELINE_AUDIT.md`](DUPLICATE_PIPELINE_AUDIT.md),
`bonbon_ai_runtime.RuntimeSelector` already implements real
Hailo/CPU/TensorRT/mock detection, selection, and fallback logging —
`AcceleratorManager` does not reimplement that algorithm. It adds two
things that didn't exist:

1. **One call surface** spanning `object_detection`, `person_detection`,
   `gesture_recognition`, `pose_estimation` — today each capability picks
   its own runtime independently across `bonbon_vision`/
   `bonbon_perception`/`bonbon_gesture`.
2. **`VisionOutputEnvelope`** — the per-output shape (`timestamp`,
   `frameId`, `runtimeSource`, `modelId`, `confidence`, `latencyMs`,
   `staleResult`) this brief's Phase 5 requires every vision output to
   carry, one level above `bonbon_ai_runtime.interface.InferenceOutput`
   (which is raw tensors + timing, not a labeled detection result).

## Staleness

`stale_after_sec` (default 0.5s, matching `bonbon_vision`'s own
`FrameThrottler` cadence rather than inventing a new number) is measured
against the frame's real `produced_at` timestamp, never against "now" —
so a delayed-but-fresh-when-captured frame is not incorrectly flagged
stale, and a genuinely old frame always is.

## Verification

`tests/edge_ai/test_accelerator_manager.py` — 6 tests: non-vision
capabilities rejected with a clear error (routes to
`runtime_selector.ModelRuntimeSelector` instead), mock-mode selection
succeeds without real hardware, the envelope carries all 7 required
fields, fresh vs. stale timing classification is correct, and `status()`
is honestly empty (never fabricated "unavailable") until `select()` has
actually been called for a capability.

## Known limitation (not fixed in this pass)

**GAP-E10, still open**: two independent object-detection stacks
(`bonbon_vision` vs `bonbon_perception`) still coexist. This module picks
neither for the caller — it exposes the same `RuntimeSelector` underneath
either stack chooses to use it. Consolidating to one canonical vision
stack is a larger, separate architectural decision, unchanged by this
brief's work.
