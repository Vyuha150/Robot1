# 3-Pi Phase 8: Systemd Deployment Per Pi

Audit before building (same discipline as Phase 7): `deployment/systemd/pi{1,2,3}/*.service`
already existed for all three Pis (18 units total, built under an earlier
BOM Workstream 5 pass), each with a real, correct `Requires=`/`After=`
dependency graph -- confirmed by reading every unit file on all three
Pis. The genuine gap was that nothing installed, started, or verified them
consistently: the only prior guidance was the hand-written, Pi-2-specific
manual commands in `docs/PI2_CONTAINER_BUILD_AND_SYSTEMD_DEPLOYMENT_COMMANDS.md`.

## What was built

`devops/scripts/pi_systemd_manager.py` -- one script, all three Pis,
matching `bootstrap_pi_network.py`'s established dry-run-by-default /
`--apply`-requires-root convention:

```bash
# See the install + start plan for any Pi (safe, no changes):
python3 devops/scripts/pi_systemd_manager.py --role pi2

# Actually install + enable (root required):
sudo python3 devops/scripts/pi_systemd_manager.py --role pi2 --apply

# Install + enable + start, in dependency order (root required):
sudo python3 devops/scripts/pi_systemd_manager.py --role pi2 --apply --start

# Check enabled/active status any time, no changes:
python3 devops/scripts/pi_systemd_manager.py --role pi2 --verify
```

Key design decision: the install/start order is **computed** from each
unit's own `Requires=` + `After=` lines (topological sort, Kahn's
algorithm) rather than hand-typed a fourth time (the compose file's own
comments and the Pi-2 doc already each encode this order once). `After=`
is included alongside `Requires=` for ordering purposes specifically
because the real unit files sometimes only encode a soft `After=` ordering
hint without a matching hard `Requires=` (e.g.
`bonbon-pi3-actuation.service` `Requires=` only `bonbon-pi3-safety.service`
but also `After=`s `bonbon-pi3-hal.service`) -- respecting both gives a
safer, more complete start sequence for this script's own purposes without
editing or reinterpreting any unit file's actual systemd semantics.

`--verify` never raises even if `systemctl` isn't installed at all (this
dev sandbox has none) -- it honestly reports every unit as not-enabled/
not-active and exits 1, never a fabricated PASS.

## Tests

`devops/tests/test_pi_systemd_manager.py`, **15 tests**:

- Pure-logic tests for the unit-file parser and topological sort,
  including a synthetic diamond-dependency case (mirrors
  `bonbon-pi2-perception-fusion.service`'s real shape: depends on both
  `vision` and `asr`, which both depend on `hal`) and a cycle-detection
  case.
- Tests run **against the real checked-in unit files** for all three Pis
  (not synthetic fixtures) confirming the actual computed order is
  correct: `hal` before `vision`, `safety` before `hal`/`actuation`,
  `base-controller` before `navigation`, `dashboard-api` before
  `dashboard-frontend`.
- `--role pi9` rejected by argparse; `--plan` (default) exercised for real
  against all three roles; `--verify` confirmed to exit non-zero honestly
  when `systemctl` is unavailable, never crash.

## Regression

`devops/tests` full suite: 119 passed, same 4 pre-existing unrelated
failures as Phase 7's report (`test_integration_test_execution_in_ci`,
`test_missing_environment_variable_fails_for_lab_robot`,
`test_dockerfiles_run_as_non_root_after_build`,
`test_ci_workflow_contains_required_pipeline_stages`) -- confirmed via
`git stash` to predate this session, left untouched (out of scope for a
systemd-deployment task).

## Not done (deliberately out of scope)

- `--apply`/`--start` were not exercised against a real systemd host --
  no such host exists in this sandbox, and doing so would require root
  plus real `docker compose` containers. `--plan`'s dry-run output was
  manually cross-checked against the real unit files instead.
- No change was made to the unit files themselves (their `Requires=`/
  `After=` split, e.g. `bonbon-pi3-actuation.service`'s soft-only
  dependency on `hal`, may be intentional or may be a real gap -- not
  decided here since it affects real systemd hard-dependency behavior on
  deployed hardware, a call this pass didn't make unilaterally).
