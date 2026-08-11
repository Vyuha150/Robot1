# Edge AI Three-Pi Deployment Report

Phase 15 summary of Phase 10's deliverable: mapping this brief's
UI/Supervisor Pi, AI Interaction Pi, Navigation/Safety Pi naming onto the
real, already-deployed three-Pi architecture, plus the launch files and
scripts to bring `bonbon_edge_ai_runtime` up correctly on each.

## Confirmed: the three-Pi split already existed and is correct

[`docs/THREE_PI_RUNTIME_AUDIT.md`](THREE_PI_RUNTIME_AUDIT.md) confirmed
`config/distributed/{pi_ui_api,pi_human_ai,pi_navigation_safety}.yaml`
already map onto this brief's naming exactly, `config/models/pi_ai_hat_plus_2_profile.yaml`'s
`ai_pi_model_load_priority` list already exists, and
`config/pi_efficiency_profile.yaml`'s 18-module `priority_order` already
closely matches this brief's Highest/Medium/Lower tiers. This phase's
[`config/edge_ai/three_pi_allocation.yaml`](../config/edge_ai/three_pi_allocation.yaml)
therefore **cross-references** these existing sources rather than
re-declaring them (verified live by
`tests/edge_ai/test_three_pi_allocation.py`, which resolves every
declared cross-reference against the real file/key it points to).

## The role table

| Pi | Real config | Runs | Forbidden |
|---|---|---|---|
| UI/Supervisor | `pi_ui_api.yaml` | dashboard, dashboard API | direct motor control, camera/mic access, LLM hosting |
| AI Interaction | `pi_human_ai.yaml` | ASR, LLM, perception, `bonbon_edge_ai_runtime` | anything beyond `/bonbon/behavior/proposal` — never a direct motor command |
| Navigation/Safety | `pi_navigation_safety.yaml` | Nav2, HAL, safety supervisor | — (sole motion command publisher) |

## Launch files and scripts (all present)

4 new launch files in [`launch/edge_ai/`](../launch/edge_ai/)
(`ai_pi_edge.launch.py`, `ui_pi_edge.launch.py`, `nav_pi_edge.launch.py`,
`full_edge_sim.launch.py`) each `_include()` the existing, already-tested
bringup launch file unchanged — `ai_pi_edge.launch.py` additionally adds
the new `edge_ai_runtime_node`. 5 new scripts in
[`scripts/edge_ai/`](../scripts/edge_ai/) (`start_ui_pi.sh`,
`start_ai_pi.sh`, `start_nav_pi.sh`, `check_three_pi_health.sh` —
delegates to the existing `scripts/health_check.sh` +
`scripts/check_inter_pi_communication.py` — and `check_edge_ai_status.sh`,
genuinely new, `ros2 topic echo --once` against each of the 6 new status
topics with a timeout).

## Verification

`tests/edge_ai/test_three_pi_allocation.py` — 6 tests: 3 roles declared,
UI Pi's forbidden list includes `direct_motor_control`, AI Pi's
`behavior_output` is proposal-only, and both cross-references
(`ai_pi_model_load_priority_source`, `resource_policy_source`) resolve to
real files/keys, not dangling pointers.
