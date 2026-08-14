# Patient-Facing UX: Graceful Degradation & First-Contact Onboarding

Covers two things a patient standing in front of the robot actually hears
or sees, as distinct from what an operator sees on the dashboard: how the
robot talks about its own degraded states, and what a first-time visitor
is told the robot can do.

## Bugs found and fixed this round

### 1. Low-confidence/ambiguous speech fell into the full RAG/LLM pipeline instead of being spoken honestly

`bonbon_perception_ai/understanding/intent_engine.py` already computes a
real, per-intent `fallback_response` (e.g. "Where would you like to go?"
for a low-confidence `navigate_to` guess, or a generic clarify line) and
publishes it on `UserIntent.fallback_response` whenever its `"clarify"`
ambiguity policy forces `intent_class` to `"unknown"`. But
`llm_orchestrator_node.py`'s `_process_intent` only special-cased **true
silence** (`is_ambiguous and not raw_text.strip()`) — a non-empty but
genuinely unclassifiable utterance (mumbled speech, ASR garble) fell
straight into the normal RAG/LLM pipeline as if it were a confident query,
risking a hallucinated answer to noise and never speaking the honest
"I didn't understand" response the system had already computed.

Fixed by adding a second short-circuit, `_handle_ambiguous()`, keyed on
`intent_class == "unknown"` specifically (not `is_ambiguous` alone, since
the `"best_guess"` ambiguity policy also sets `is_ambiguous=True` while
keeping a real, usable `intent_class` — that case must still reach the
full pipeline, or `best_guess`'s entire purpose is defeated). 5 new tests
in `ros2_ws/src/bonbon_llm/tests/test_llm_orchestrator.py`
(`TestProcessIntentAmbiguousUnknownSkipsRagAndLlm`), including one that
specifically protects the `best_guess` policy from being broken by this
fix.

### 2. Fallback phrasing was written for a café robot, not a hospital

`bonbon_llm/prompts/response_templates.py` and `bonbon_llm/README.md`
were still literally café copy ("I can take orders, answer menu
questions", "navigate the café") left over from an earlier version of
this project. Also, the `emergency` template told patients to "call 995"
— Singapore's emergency number, meaningless for an India deployment and
inconsistent with the fact that the orchestrator already dispatches an
internal `alert_safety` behavior and pages staff directly (see
`_process_intent`'s emergency-route branch) — telling a patient to call
an external number on top of that is actively wrong guidance.

Reworded every template (`unknown_request`, `navigation_denied`,
`actuation_denied`, `silent`, `out_of_scope`, `emergency`, `greeting`) to
hospital-appropriate language: departments, appointments, tokens, staff.
`emergency`'s long variant now correctly reflects that staff are already
being alerted and cites India's real unified emergency number (112) only
as a fallback. No existing test asserted exact template content (only
presence/length), so this was a safe content-only change — reverified
against `test_llm_orchestrator.py::TestFallbackTemplates` (unchanged, all
passing).

### 3. First-contact greeting never explained what the robot does

Both real greeting paths — `multi_person_behavior_selector
.decide_arrival_greeting()` (multi-person path, gated on
`lifecycle_state` + wave gesture) and `behavior_engine_node
._dispatch_greeting()` (older single-person path, fires on the
`SpatialEntity` `not was_present → present` transition) — spoke the
identical generic line, `"Hello! I'm BonBon. How can I help you today?"`,
regardless of whether this was someone's first-ever encounter with the
robot. For many people in an Indian hospital, this may be the first
service robot they have ever interacted with, and a bare "hello" gives
no hint what to ask it for.

Fixed differently in each path, matching what each path can actually
know:
- `decide_arrival_greeting()` now checks `hs.known_person_id` (real,
  wired since rule 2's recall-buffer greeting) and gives **first-time
  visitors** (`known_person_id` empty) a short capability orientation
  — departments, appointments/tokens, general questions — while
  **recognized returning visitors** keep the original short greeting, so
  regulars aren't re-onboarded on every visit.
- `_dispatch_greeting()` has no known/unknown distinction available
  (`SpatialEntity` carries no recall-buffer identity) and, by
  construction, only ever fires on a genuine first contact for the
  session (`not was_present`) — so it always speaks the fuller
  orientation text unconditionally.

2 new tests in `bonbon_behavior_engine/tests/test_multi_person_behavior_selector.py`
(`test_first_time_visitor_gets_capability_orientation`,
`test_known_visitor_gets_short_greeting_not_full_orientation`).

## Known gap, deliberately not fixed this round: hardware/network faults never reach the patient

`bonbon_fault_manager` (unified fault registry) and
`bonbon_distributed_network_monitor` (clock-offset/peer-link alerting)
have zero TTS dispatch anywhere — confirmed by grep, zero hits. Their
output (`degraded_mode`, `component_health`, the fault registry) reaches
only the operator dashboard via `bonbon_operator_api`'s WebSocket
channels (`websocket/status_broadcasters.py`), never the person standing
in front of the robot. So today: a mumbled question gets an honest
"I didn't understand" (fix #1 above); an actual system fault (Pi link
lost, hardware over threshold) gets **no spoken acknowledgment at all** —
the robot just goes quiet or keeps behaving oddly with no explanation.

This was deliberately left unfixed rather than wired silently: giving
`bonbon_fault_manager` new authority to speak directly to patients is an
architecture decision (which fault severities warrant interrupting a
patient interaction, how to avoid repeatedly announcing a known ongoing
issue, whether this goes through the existing TTS priority/authorization
path in `bonbon_llm`) that needs an explicit choice, not something to
bake in as a side effect of a UX audit. Flagged here for a future
task, same posture as the Sarvam licensing blocker and the disconnected
`bonbon_speech_ai` stack noted in `docs/SPEECH_AI_UPGRADE_REPORT.md`.

## Verification

- `ros2_ws/src/bonbon_llm/tests/test_llm_orchestrator.py`: 45/45 passing
  (isolated run — see repo-wide note on combined-directory pytest
  collisions in `docs/HUMAN_STATE_FUSION.md`'s test history and prior
  session notes; every `bonbon_llm` test file also passes individually).
- `ros2_ws/src/bonbon_behavior_engine/tests/`: 179/179 passing (was 177).
- `ruff check` / `black --check`: clean on all touched files.
