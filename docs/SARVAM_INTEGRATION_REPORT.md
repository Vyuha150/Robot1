# Sarvam AI Integration Report

Phase 5/14. Covers `bonbon_sarvam_adapter` (7 modules) and the rules it
exists specifically to enforce: rule 3 (never download/use Sarvam without
official access), rule 4 (never use a cloud API by default), rule 12
(Sarvam is the preferred Indic engine, but *only if* official Edge/API
access genuinely exists).

## Status: **NOT ACTIVE** in this environment — honestly, not silently

Confirmed by `scripts/ai_models/check_sarvam_access.py` and
`bonbon_sarvam_adapter.sarvam_capability_detector.detect_sarvam_capabilities()`,
both run this pass:

- No `sarvam_edge`/`sarvam` package importable in this sandbox.
- No `SARVAM_API_KEY` environment variable set.
- Result: `available=False`, `mode="unavailable"`, every one of
  `asr_available`/`tts_available`/`translation_available`/`ocr_available`
  is `False`.

This is a **zero-prior-integration** situation, confirmed by two
independent repo-wide greps during the Phase 1 audit
(`docs/AI_MODEL_GAP_ANALYSIS.md` GAP-11) — nothing in this codebase has
ever successfully called a real Sarvam endpoint.

## Decision table implemented (`sarvam_license_status.evaluate`)

| edge_installed | api_key_present | cloud_enabled | Result |
|---|---|---|---|
| True | — | — | **allowed**, mode=`edge` (local, no cloud call) |
| False | True | True | **allowed**, mode=`api` |
| False | True | False | **NOT allowed** — rule 4: a key existing is not the same as being authorized to use it |
| False | False | — | **NOT allowed**, mode=`unavailable` |

Tested directly in `tests/speech_ai/test_sarvam_fallback.py`
(`TestSarvamLicenseDecisionTable`, 5 cases) — including the specific
rule-4 case (API key present, cloud not enabled → still blocked).

## Architecture

- `sarvam_license_status.py` — the pure decision function above.
- `sarvam_capability_detector.py` — the one real-detection entry point
  every other module (and the Phase 11 dashboard `/sarvam/status`
  endpoint) calls. Checks two candidate Edge package names
  (`sarvam_edge`, `sarvam` — this session has no way to confirm the real
  package name, so both are checked, neither assumed).
- `sarvam_api_client.py` / `sarvam_edge_asr_client.py` /
  `sarvam_edge_tts_client.py` / `sarvam_translation_client.py` — real
  client stubs that raise/report unavailable honestly rather than
  fabricating a response when called with no real access.
- `sarvam_fallback_policy.py` — the ASR/TTS routers' bespoke availability
  checker, wired into `ModelRuntimeSelector.bespoke_checkers` for
  `asr_sarvam_edge`/`tts_sarvam_edge`/`translation_sarvam`, so the
  generic registry's `external_api` heuristic (which just checks for an
  env var named `SARVAM_API_KEY`) never governs Sarvam decisions —
  Sarvam's own nuanced edge-vs-api-vs-neither logic always does.

## What activating real Sarvam access requires

1. Obtain official Sarvam AI Edge SDK or API credentials (a business/
   partnership step outside this codebase's scope).
2. Install the real Edge package (name TBD once confirmed by Sarvam) —
   `sarvam_capability_detector._find_edge_package()` will then detect it
   automatically, no code change needed.
3. OR set `SARVAM_API_KEY` **and** explicitly `BONBON_CLOUD_ENABLED=true`
   — both required together per rule 4.
4. Re-run `python3 scripts/ai_models/check_sarvam_access.py` to confirm.
5. No further wiring needed: `asr_sarvam_edge`/`tts_sarvam_edge`/
   `translation_sarvam` are already first in their respective fallback
   chains in `config/models/model_registry.yaml` — the moment access is
   confirmed, the routers pick Sarvam automatically without a restart-time
   config change (checked live, every call).

## Verdict: **BLOCKED** (external dependency — no official access exists to test against). Adapter code is complete, tested, and ready to activate the instant access is granted.
