# Edge AI Model Download Report

Phase 15 summary of Phase 11's deliverable: LLM/speech model download and
install scripts under [`scripts/edge_ai/`](../scripts/edge_ai/), plus the
"do not blindly download everything" rule this brief explicitly requires.

## Delegation, not duplication

Per this repo's established "delegate to canonical script" convention
(e.g. `scripts/health_check.sh` → `devops/scripts/health_check.sh`), 5 of
the 6 new scripts are thin wrappers over the already-existing, already-
tested `scripts/ai_models/*` equivalents: `download_qwen25_05b.sh`,
`install_sherpa_onnx.sh`, `install_piper_tts.sh`, `install_mediapipe.sh`,
`check_sarvam_access.py`. Each was smoke-tested live and confirmed to
delegate correctly with honest output.

`check_hailo_runtime.sh` is genuinely new — it wraps
`bonbon_ai_runtime.hailo_device_detector.HailoDeviceDetector` (real
detection logic, not a third reimplementation) via an inline
`python -c`, with a `cygpath -w` fix for the Windows/Git-Bash
POSIX-path-in-a-Python-string-literal translation issue this sandbox
surfaced (falls through unchanged on the real Linux Pi target, where
`cygpath` doesn't exist and the path is already correct).

## "Do not blindly download everything" — enforced, not just stated

`ModelDownloader.download()` refuses to dispatch anything whose
`download_type` isn't one of `{ollama, pip, git, wget}` — this brief's 3
new capabilities (`human_state_fusion`, `intent_classification`,
`assistant_guardrails`) are all declared `download_type: unavailable`
(deliberately: none has a real ML model to fetch — see
[`EDGE_AI_MODEL_STRATEGY_REPORT.md`](EDGE_AI_MODEL_STRATEGY_REPORT.md)),
and `LicenseChecker` itself rejects that `download_type` before dispatch
is even considered ("no known source exists"). Verified directly by
`tests/edge_ai/test_download_plan.py`, which attempts to force-download
all 6 new registry entries with `explicit_approval=True` and confirms
none succeeds.

## Verification

`tests/edge_ai/test_download_plan.py` — 3 tests: the merged registry's
download plan covers every entry (base 39 + edge_ai 6), the 3 new
capabilities are never auto-dispatched, and every named Phase 11 script
exists on disk.
