# Real-World Interaction Scenarios

The 10 example behaviors from the multi-person perception brief, as
implemented in `bonbon_behavior_engine`'s
[`multi_person_behavior_selector.py`](../ros2_ws/src/bonbon_behavior_engine/bonbon_behavior_engine/core/multi_person_behavior_selector.py).
Every rule here only PROPOSES a behavior — it is dispatched through the
existing safety-gated `ProposalEvaluator.evaluate()` path, the same one the
pre-existing single-person callbacks already use. None of these rules can
bypass the Safety Supervisor.

## 1. New person arrives and waves → greet

`decide_arrival_greeting`: fires once per `person_track_id` when
`lifecycle_state` is `present`/`reappeared` and `current_gesture == 'wave'`.
Forgotten on departure so a genuinely later arrival is never silently
skipped.

## 2. Known person speaks → respond by name (if privacy allows)

`decide_known_person_greeting`: requires `known_person_id` non-empty,
`active_speaker_status == 'speaking'`, and the new `privacy_mode` parameter
set to allow it. Fires once per session per person.

## 3. Person leaves → close session after timeout

`decide_departure_close_session`: fires on `lifecycle_state == 'left_scene'`.
`bonbon_multi_person_tracker`'s own `loss_grace_sec` IS the "after timeout"
— `left_scene` only fires once that grace window has already elapsed, so no
second timeout layer was added here.

## 4. New person replaces old person → new temporary profile

Handled for free by `person_track_id` independence — every tracked person
already gets their own identity-lifecycle record from
`bonbon_multi_person_tracker`. Verified by test
(`MultiPersonSceneManager` tests: a departed known person's later return
gets a brand-new `person_track_id`, never a resurrected one), not by new
behavior-engine code.

## 5. Multiple people speak → focus on the active speaker

`select_focus_person`: priority order is speaking > `active_interaction`
lifecycle > highest `urgency_level` > most recently reappeared. When two
people speak simultaneously, the higher-urgency one wins focus.

## 6. Stop palm from any person nearby → pause and ask confirmation

`decide_safety_gesture_response`: checked across **all** tracked people
every cycle, regardless of who currently has focus — a safety gesture from
a bystander must interrupt whatever the robot is doing with the focus
person. Maximum urgency (1.0).

## 7. Angry/stressed voice → calm supportive style

`decide_calm_supportive_response`: deliberately limited to
`angry`/`frustrated`. `distressed`/`fearful` are excluded here because the
OLDER single-focus `HumanEmotionState` callback path
(`EmotionAwareResponsePlanner` via `_dispatch_emotion_response`) already
handles those exclusively — covering them in both places would
double-dispatch the same event.

## 8. Confused expression + question → slow explanation

`decide_confused_question_response`: requires `emotional_state == 'confused'`
AND `text_intent` in `{ask_question, help_request}` — both signals must
agree; confusion alone or a question alone doesn't trigger it.

## 9. Child near robot → slow movement, no sudden gestures

`apply_child_safety_modifier`: applied to whatever OTHER decision was
already made, not a standalone proposal. Caps `speed_scale` at 0.7 and
downgrades any non-gentle gesture to `listening_pose`. Child detection
bridges `person_track_id → PersonTrack.raw_track_id → SpatialEntity.person_category`
(an existing `bonbon_spatial` signal).

## 10. Person points a direction → ask confirmation, use spatial context

`decide_pointing_confirmation`: fires on `pointing_left`/`pointing_right`/
`pointing_forward`, asking "did you mean over there, to the {direction}?"
rather than acting on the pointing gesture directly.

## Cross-cutting rules verified by every behavior

- **Never mix identities** — every candidate carries a `person_track_id`;
  `decide_safety_gesture_response` is the only rule that scans all people,
  and it still attributes the resulting action to the SPECIFIC person who
  gestured, not the current focus person.
- **LLM never directly acts** — every proposal, regardless of which rule
  produced it, still passes through `ProposalEvaluator`/`CommandRiskClassifier`.
- **Safety Supervisor blocks unsafe actions** — `ProposalEvaluator` rejects
  `navigate`/`approach`/`gesture` proposals at DANGER level and above (the
  `gesture` case was a real gap found and fixed while building the Phase 10
  scenario suite — see [TESTING_PERCEPTION_INTELLIGENCE.md](TESTING_PERCEPTION_INTELLIGENCE.md)).

## Tests

35 tests in
[`test_multi_person_behavior_selector.py`](../ros2_ws/src/bonbon_behavior_engine/tests/test_multi_person_behavior_selector.py),
one per behavior rule plus the focus-selection priority order and the child-
safety modifier. Full existing 113-test suite unaffected — the older
single-focus callbacks are untouched.
