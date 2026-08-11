# Edge AI Event-Driven Processing Report

Phase 15 summary of Phase 9's deliverable: verifying and enforcing this
brief's exact per-capability event-driven rules (ASR/LLM/TTS/object-
detection/gesture/emotion/RAG/navigation must react to real events, not
poll continuously).

## Confirmed already correct (no fix needed)

- **ASR**: `bonbon_speech_ai/speech_pipeline.py`'s `vad_confirmed` gate is
  genuinely wired — ASR never runs continuously.
- **Object detection**: `bonbon_vision/preprocessing/frame_throttler.py::FrameThrottler`
  is genuinely enforced.
- **LLM**: never called first — `pi_human_ai.yaml`'s
  `resolution_order: [rule_engine, rag, llm]` correctly places it last
  (though not yet *enforced* by live code — see GAP-E8 below).
- **Gesture/emotion**: routed through `TaskRouter`'s safety-relevant vs.
  social/low-confidence branches (Phase 4), never acted on unconditionally.

## One real bug found and fixed (GAP-E13)

**TTS never actually checked the phrase cache first.** `TTSRouter.speak()`
always consulted the full runtime-availability chain regardless of
whether the requested text was one of the 6 known cached hospital
phrases — a known phrase was re-synthesized via Piper on **every single
call**, measured at 2.5–5.8s of real, avoidable latency in this repo's
own earlier benchmark runs. Directly violated Phase 9's "use cached
phrase first, synthesize only if cache miss" rule. Fixed: `speak()` now
does a real file-existence check against the phrase cache **before**
touching `self._selector` at all, only falling through to the engine
chain on a genuine miss. A related honesty gap was fixed alongside it:
the cached-phrase invoker used to return a path string without checking
the file actually existed.

## One rule confirmed still violated, not fixed (GAP-E14)

**RAG has no exact-match-first step.** `bonbon_llm/core/rag_retriever.py::retrieve_with_scores()`
goes straight to embedding-based cosine similarity for every query — no
exact-string-match short-circuit exists before vector search,
contradicting Phase 9's "RAG: exact match first, vector search second"
rule. Not fixed: the right shape for "exact match" (against document
titles? a canonical FAQ question list?) is a real design decision
deserving its own pass, not a rushed change to the retrieval core. The
new `RagResultCache` (Phase 6) provides an adjacent but different
short-circuit (identical prior query+context, not exact-match-on-content)
— it does not substitute for this.

## Verification

`tests/edge_ai/test_event_driven_processing.py` — 10 tests: a GAP-E2
regression guard (navigation only dispatches from an approved command,
verified via `ast`-based static source inspection rather than importing
`navigation_node.py`, which requires real `rclpy`), a GAP-E13 regression
guard (TTS checks the cache before touching the selector, verified via
source-order inspection), LLM-last-resort config checks, RAG cache-first
behavior, gesture/emotion event-driven routing, and confirmation that
`bonbon_vision`'s `FrameThrottler` module exists (its own deep behavioral
coverage lives in `bonbon_vision/tests/test_frame_throttler.py`, not
duplicated here).
