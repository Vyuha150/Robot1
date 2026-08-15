# Redundant Code Removal Plan

**Phase 3 companion to `DUPLICATE_PIPELINE_REPORT.md`.** Only 2 items came out of the duplicate-pipeline analysis needing a plan — the search was thorough, and the codebase's actual duplication surface turned out to be much smaller than the package-naming patterns initially suggested.

## 1. Remove `bonbon_perception` (dead duplicate of `bonbon_vision`)

**What:** The entire `ros2_ws/src/bonbon_perception/` package.

**Why it's safe:**
- Its launch file is already renamed `launch/perception.launch.py.disabled` — someone already took it out of service.
- `setup.py`'s `console_scripts` entry point is empty — even if something tried to `ros2 run` it, there's no executable registered.
- Zero repo-wide `import bonbon_perception` / `from bonbon_perception` hits — nothing depends on it as a library either.
- It is not referenced in any `docker-compose.*.yml`, any `*_bringup` launch file, or any `launch/edge_ai/*.launch.py`.

**Plan:**
1. Phase 10: quarantine to `_archive/quarantine_cleanup_YYYYMMDD/bonbon_perception/` with a documented restore command (`git mv` back, or `cp -r` from the archive), not a hard delete yet.
2. Phase 11: run the full pytest suite with the package quarantined; confirm zero new failures (expected, since nothing imports it).
3. Phase 11: run `git status`/`grep` once more post-quarantine to catch anything the earlier passes might have missed (defense in depth).
4. Only after that clean re-check, permanently remove in Phase 11's final cleanup step. Given the strength of the "already disabled, zero importers" evidence, this is one of the lowest-risk removals in the whole plan.

**What NOT to do:** Don't delete `bonbon_vision` by mistake — it is the live package with the confusingly similar purpose. Triple-check the package name before any `rm -rf` or `git rm -r`.

## 2. Auth duplication between `bonbon_operator_api` and `bonbon_patient_kiosk` — flagged, not removed

**What:** `bonbon_patient_kiosk/auth/auth_manager.py` independently re-implements the same JWT/PBKDF2/SQLite pattern as `bonbon_operator_api/auth/auth_manager.py`, per its own docstring ("Pattern-copied from...").

**Why this is NOT part of this cleanup pass's removal scope:**
- The two systems have genuinely different role models (operator_api: viewer/operator/engineer/admin; patient_kiosk: staff/admin) and separate databases — a merge is a real feature-level refactor with security implications, not a mechanical dedup.
- Extracting a shared auth library correctly requires full test coverage of *both* role sets before and after, which is beyond a cleanup pass's scope (the brief's own rule: "Do not merge duplicate utilities" without tests protecting the decision, and this merge needs new tests written, not just existing ones re-run).
- Getting this wrong could weaken access control on either the staff dashboard or the patient kiosk — this is exactly the kind of change that needs to be its own reviewed task, not a line item in a larger cleanup.

**Recommendation:** Log as a follow-up engineering task ("Extract shared auth library from bonbon_operator_api and bonbon_patient_kiosk, with full role-matrix test coverage for both"), not acted on here. No files touched in this cleanup pass for this finding.

## Everything else: no removal plan needed

Every other pipeline category in `DUPLICATE_PIPELINE_REPORT.md` passed the "exactly one owner" check with real evidence. The two launch mechanisms (`*_bringup` vs `launch/edge_ai/`) are carried forward to Phase 8 for systemd-service cross-referencing before any conclusion — not assumed to need consolidation.
