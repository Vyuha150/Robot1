# Unsafe Control Path Fix Report

**Phase 5.** The cleanup brief's rule for this document: "Any dangerous direct-control path must be fixed immediately." `SAFETY_BYPASS_REPORT.md` found **zero dangerous direct-control paths** anywhere in the 44-package tree — every motion-intent source correctly routes through the single gated chain. This document is therefore short by design: there is nothing to fix in this category, and fabricating a fix for a problem that doesn't exist would itself violate this audit's "don't guess, don't fake" rule.

## Fixes applied in this phase: none required

No motor, servo, or Nav2 control path needed correction. This is the intended, positive outcome of Phase 5 — confirming the architecture holds, not finding and patching a hole.

## Related items, correctly triaged to other phases (not fixed here, and here's why)

### 1. Fake dashboard success on `restart_module` and `set_config` — Phase 9, not Phase 5
These two endpoints (`diagnostics_api.py`, `config_api.py`) return HTTP 200/success even when their underlying not-implemented bridge calls fail. This is a **dashboard truthfulness** defect (the brief's own Phase 9 rules: "Never show OK unless real data supports OK"), not an unsafe control path — neither endpoint touches motion, actuation, or any safety-relevant hardware. Fixing it here would blur Phase 5's safety-specific scope with Phase 9's truthfulness scope; the real fix (making both endpoints honestly propagate failure, matching the `_check_bridge_result` pattern already used correctly by `command_api.py`) is implemented in Phase 9 alongside the rest of the dashboard-truthfulness work, with its own tests.

### 2. Watchdog auto-restart placeholder — feature gap, not a safety fix
`watchdog_node.py`'s `_attempt_restart()` doesn't yet call a real restart service (honestly commented as a placeholder in the code itself). This does not weaken the safety chain — stale-critical-node detection still correctly reaches `bonbon_distributed_safety` for degraded-mode decisions regardless of whether auto-restart works. Implementing real auto-restart is a feature addition, not a bug fix, and is out of scope for a cleanup pass — noted for a future task, not built here.

### 3. `bonbon_actions`' unconsumed `ExecuteMotionSequence.action` — preventive note, not a current risk
No node in the repo consumes this action interface, so there is nothing to fix today — an unused interface cannot be misused. Recorded here so that if a future task adds a consumer, that consumer's design is reviewed against this report's safety-chain requirements from the start (proposal → gateway → supervisor → execution), rather than the review happening after the fact.

## Verification

`SAFETY_BYPASS_REPORT.md`'s conclusions were reached via direct `grep`/code-read evidence, not inference from documentation. The full pytest baseline (`CURRENT_BUILD_TEST_BASELINE.md`, 1013 passed / 15 skipped) already covers this repo's existing safety-separation tests (e.g. the GAP-E6 topic-graph safety-separation test from an earlier session, confirmed still present and passing in this session's baseline run) — Phase 12's regression pass will re-confirm these specific tests by name rather than relying on the aggregate count alone.
