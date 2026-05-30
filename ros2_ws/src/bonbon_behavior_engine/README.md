# bonbon_behavior_engine

The **central behaviour decision engine** for the BonBon service robot. It is
the single authority that fuses every perceptual signal — emotion, gesture,
spatial reasoning, speech intent, LLM proposals, safety state — into safe,
validated behaviour decisions, and dispatches them through the normal
safety-gated execution path (actuation, TTS, navigation, operator alerts).

## The core safety contract

> **The LLM never directly controls navigation or actuation.**

Every LLM output is risk-classified and passed through the `LLMCommandGate`,
which only ever produces a *structured proposal*. That proposal is then
re-validated by the `ProposalEvaluator` against the live safety level and
operating mode before anything is dispatched. An unsafe command can never
become an approved motion — it is rejected, downgraded to speech/clarification,
or escalated to a human operator.

---

## Responsibilities

| Capability | Module |
|---|---|
| 7-state behaviour FSM with legal-transition enforcement | `core/behavior_state_machine.py` |
| Pattern-based command risk classification (LLM-free, deterministic) | `core/command_risk_classifier.py` |
| LLM-output → safe structured proposal gate | `core/llm_command_gate.py` |
| Final proposal validation (safety level, mode, rate limit) | `core/proposal_evaluator.py` |
| Emotion → response style / gesture / TTS planning | `core/emotion_response_planner.py` |
| Spatial hint / alert → behaviour response | `core/spatial_response_planner.py` |
| Deduplicating, escalating operator-alert manager | `core/operator_alerter.py` |
| ROS2 LifecycleNode orchestration | `nodes/behavior_engine_node.py` |

---

## Architecture

```
 affective ─/bonbon/affective/state─┐
 gesture ───/bonbon/gesture/events──┤
 spatial ───/bonbon/spatial/hints───┤    ┌──────── BehaviorEngineNode ────────┐
 spatial ───/bonbon/spatial/alerts──┼───►│ EmotionResponsePlanner             │
 spatial ───/bonbon/spatial/entities┤    │ SpatialResponsePlanner             │
 speech ────/speech/command─────────┤    │ LLMCommandGate → ProposalEvaluator │
 safety ────/bonbon/safety/state────┘    │ BehaviorStateMachine (FSM)         │
                                         │ OperatorAlerter (dedup/escalate)   │
                                         └────────────────────────────────────┘
            ┌──────────────┬───────────────┬─────────────────┬────────────────┐
            ▼              ▼               ▼                 ▼                ▼
 /bonbon/behavior/   /bonbon/behavior/  /bonbon/tts/   /bonbon/behavior/  /bonbon/operator/
   actuation           decision           request        proposal           alerts
 (ActuationGesture) (BehaviorDecision)  (TTSRequest)  (BehaviorProposal)   (RiskEvent)
```

Every dispatched actuation/navigation command is **advisory** — the Safety
Supervisor (`bonbon_safety`) and the actuation/navigation nodes enforce their
own independent safety gates downstream.

---

## Topics & Services

### Subscribed
| Topic | Type | Purpose |
|---|---|---|
| `/bonbon/safety/state` | `bonbon_msgs/SafetyState` | gate all decisions |
| `/bonbon/affective/state` | `bonbon_msgs/HumanEmotionState` | emotion-aware responses |
| `/bonbon/gesture/events` | `bonbon_msgs/GestureEvent` | gesture responses |
| `/bonbon/spatial/hints` | `bonbon_msgs/SocialNavigationHint` | social navigation responses |
| `/bonbon/spatial/alerts` | `bonbon_msgs/RiskEvent` | restricted-zone / blockage / collision |
| `/bonbon/spatial/entities` | `bonbon_msgs/SpatialEntity` | presence / greeting triggers |
| `/speech/command` | `bonbon_msgs/SpeechCommand` | speech intent |

### Published
| Topic | Type | Purpose |
|---|---|---|
| `/bonbon/behavior/actuation` | `bonbon_msgs/ActuationGesture` | gesture requests → actuation |
| `/bonbon/tts/request` | `bonbon_msgs/TTSRequest` | speech requests → TTS |
| `/bonbon/behavior/decision` | `bonbon_msgs/BehaviorDecision` | auditable decision record |
| `/bonbon/behavior/proposal` | `bonbon_msgs/BehaviorProposal` | pre-validation proposals |
| `/bonbon/operator/alerts` | `bonbon_msgs/RiskEvent` | **operator console escalations** |

### Services
| Service | Type | Purpose |
|---|---|---|
| `~/evaluate_command` | `bonbon_srvs/EvaluateCommand` | external command safety check |
| `~/set_mode` | `bonbon_srvs/SetMode` | switch operating mode |
| `~/health_check` | `bonbon_srvs/HealthCheck` | health snapshot |

---

## Behaviour state machine

`IDLE → GREETING → INTERACTING → NAVIGATING → SERVING → ALERTING → RETURNING`
(7 states, only legal transitions permitted). Safety DANGER+ or a medical
emergency forces `ALERTING`.

## Spatial responses

`SpatialResponsePlanner` maps each incoming spatial signal to a concrete
response (pause navigation, perform a gesture, speak, escalate):

| Signal | Response |
|---|---|
| hint `stop` | pause nav + stop gesture + "Excuse me" (escalate if urgency ≥ 0.9) |
| hint `retreat` | retreat gesture + apology |
| alert `restricted_zone_entry` | announce + **operator escalation (HIGH)** |
| alert `path_blocked` | pause + "May I pass?" |
| alert `collision_risk` | pause + stop gesture + urgent "Watch out" |

## Operator alerting

`OperatorAlerter` deduplicates by `(alert_type, subject_id)` within
`operator_alert_cooldown_sec`, but a **severity escalation fires immediately**.
Medical emergencies are always CRITICAL. Alerts are published as `RiskEvent` on
`/bonbon/operator/alerts` for the dashboard.

---

## Running

```bash
cd ros2_ws && colcon build --packages-select bonbon_behavior_engine
ros2 launch bonbon_behavior_engine behavior_engine.launch.py

# Safety-check an arbitrary command
ros2 service call /behavior_engine_node/evaluate_command \
  bonbon_srvs/srv/EvaluateCommand "{command_text: 'go to the lobby', source: 'operator'}"

ros2 topic echo /bonbon/operator/alerts
```

Runs fully in **simulation/mock mode** — it consumes only messages from the
perception/AI stack and emits proposals; no hardware required.

---

## Testing

```bash
cd ros2_ws/src/bonbon_behavior_engine
python -m pytest tests/ -q          # 113 tests
```

- `test_behavior_state_machine.py` — FSM legality
- `test_command_risk_classifier.py` — risk patterns
- `test_llm_command_gate.py` — LLM → safe proposal gating
- `test_emotion_response_planner.py` — emotion → response
- `test_operator_alerter.py` — dedup / escalation / cooldown
- `test_spatial_response_planner.py` — hint/alert → response
- `tests/integration/test_behavior_integration.py` — full chain + LLM safety invariant

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Commands always rejected | Safety level ≥ DANGER, or actuation/tts disabled | Check `/bonbon/safety/state`; only speech/alert allowed in FAULT. |
| LLM command does nothing | Gate downgraded it (unsafe / ambiguous) | Inspect `/bonbon/behavior/decision`; see `rejection_reason`. |
| No operator alerts | Dedup cooldown active, or severity not escalating | Lower `operator_alert_cooldown_sec`; verify upstream alert severity. |
| Duplicate operator alerts | Cooldown too short | Raise `operator_alert_cooldown_sec` (default 10 s). |
| Robot never greets | No `SpatialEntity`/person present, or FSM not in IDLE | Check spatial entities; FSM must allow IDLE→GREETING. |
| Spatial stop ignored | Not in NAVIGATING state | Pause is advisory; navigation enforces its own stop via safety gate. |
| Gestures/TTS not dispatched | `actuation_enabled` / `tts_enabled` false in SafetyState | Confirm safety supervisor enables them. |

### Diagnostics

`~/health_check` reports the current FSM state, operating mode, safety level,
LLM-gate approval ratio, and operator-alerter counters
(`requested` / `sent` / `suppressed`). Every decision is published on
`/bonbon/behavior/decision` for audit.
