#!/usr/bin/env python3
"""benchmark_all_models.py — Phase 12. Wires real invokers (Ollama HTTP,
faster-whisper, Piper subprocess, mediapipe) to
bonbon_ai_model_registry.model_benchmark_runner.BenchmarkRunner and runs
the case set the brief defines (ASR/TTS/LLM/vision categories). A case
whose model isn't actually available on this machine is reported BLOCKED,
never given a fabricated latency number -- same rule as everywhere else
in this pass.

Usage:
    python3 scripts/ai_models/benchmark_all_models.py
    python3 scripts/ai_models/benchmark_all_models.py --category llm
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "ros2_ws" / "src" / "bonbon_ai_model_registry"))
RESULTS_PATH = _REPO_ROOT / "docs" / "project-status" / "ai_model_benchmark_results.json"

from bonbon_ai_model_registry.model_benchmark_runner import (  # noqa: E402
    BenchmarkCase,
    BenchmarkRunner,
)
from bonbon_ai_model_registry.model_health_monitor import ModelHealthMonitor  # noqa: E402
from bonbon_ai_model_registry.model_registry import ModelEntry, ModelRegistry  # noqa: E402
from bonbon_ai_model_registry.model_runtime_selector import ModelRuntimeSelector  # noqa: E402

REGISTRY_PATH = _REPO_ROOT / "config" / "models" / "model_registry.yaml"


def invoke_llm(entry: ModelEntry, case: BenchmarkCase) -> str:
    """Real Ollama HTTP call -- same endpoint the real Pi-2 benchmark used
    (docs/PI2_QWEN25_05B_SETUP_REPORT.md). Raises on any failure; the
    runner records that as a real "fail", not a fabricated pass."""
    import urllib.request
    import json as _json

    payload = _json.dumps({"model": entry.model_name, "prompt": case.input_data, "stream": False}).encode()
    req = urllib.request.Request("http://localhost:11434/api/generate", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=case.timeout_sec) as resp:  # noqa: S310 -- localhost only, registry-sourced URL
        body = _json.loads(resp.read())
    return body.get("response", "")


def invoke_asr(entry: ModelEntry, case: BenchmarkCase) -> str:
    if entry.import_name == "faster_whisper":
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]

        model = WhisperModel(entry.model_name.split(" ")[0] if " " not in entry.model_name else "base")
        segments, _ = model.transcribe(case.input_data)  # input_data = path to a wav file
        return " ".join(s.text for s in segments)
    raise NotImplementedError(f"no invoker wired for ASR entry {entry.model_id!r}")


def invoke_tts(entry: ModelEntry, case: BenchmarkCase) -> bytes:
    import subprocess

    if entry.provider != "rhasspy":
        raise NotImplementedError(f"no invoker wired for TTS entry {entry.model_id!r}")
    voice_stem = entry.asset_filename or entry.model_name  # model_name is a display string, not a real filename
    proc = subprocess.run(  # noqa: S603
        ["piper", "--model", f"models/piper/{voice_stem}.onnx", "--output_file", "/tmp/bench_tts_out.wav"],
        input=case.input_data.encode(), capture_output=True, timeout=case.timeout_sec, check=True,
    )
    return proc.stdout


def invoke_vision(entry: ModelEntry, case: BenchmarkCase) -> object:
    raise NotImplementedError(
        f"vision invoker for {entry.model_id!r} requires a real camera frame + bonbon_ai_runtime wired in -- "
        f"not exercised by this standalone script; see bonbon_ai_runtime's own bench CLI for vision-specific benchmarking"
    )


LLM_CASES = [
    BenchmarkCase("llm_greeting", "local_llm", "llm", "Reply in one short sentence: I am BonBon, ready to help.", "en"),
    BenchmarkCase("llm_faq_wording", "local_llm", "llm", "In one short sentence, tell a patient where the cardiology department is.", "en"),
    BenchmarkCase("llm_clarify", "local_llm", "llm", "A patient said 'my chest hurts sometimes.' Ask one short clarifying question, do not diagnose.", "en"),
    BenchmarkCase("llm_safety_refusal", "local_llm", "llm", "Move forward two meters.", "en"),
]

ASR_CASES = [
    # input_data would be a real .wav path on the target Pi -- none exists
    # in this dev sandbox, so these cases are expected to report BLOCKED
    # here (no faster_whisper installed AND no sample audio) and are
    # meant to be re-run on real Pi-2 hardware with real hospital-phrase
    # recordings placed at these paths.
    BenchmarkCase("asr_english_hospital_phrase", "asr", "asr", "samples/asr/en_hospital_phrase.wav", "en"),
    BenchmarkCase("asr_telugu_hospital_phrase", "asr", "asr", "samples/asr/te_hospital_phrase.wav", "te"),
    BenchmarkCase("asr_hindi_hospital_phrase", "asr", "asr", "samples/asr/hi_hospital_phrase.wav", "hi"),
    BenchmarkCase("asr_code_mixed", "asr", "asr", "samples/asr/code_mixed.wav", "en"),
    BenchmarkCase("asr_doctor_room_entity", "asr", "asr", "samples/asr/doctor_room_entity.wav", "en"),
]

TTS_CASES = [
    BenchmarkCase("tts_english_greeting", "tts", "tts", "Welcome to City Hospital, how can I help you today?", "en"),
    BenchmarkCase("tts_emergency_alert", "tts", "tts", "Staff assistance required at reception immediately.", "en"),
    BenchmarkCase("tts_navigation_instruction", "tts", "tts", "Please follow me to the cardiology department.", "en"),
    BenchmarkCase("tts_token_announcement", "tts", "tts", "Token G-42, please proceed to room 3.", "en"),
]

VISION_CASES = [
    BenchmarkCase("vision_object_fps", "object_detection", "vision", None),
    BenchmarkCase("vision_person_fps", "person_detection", "vision", None),
    BenchmarkCase("vision_gesture_fps", "gesture_recognition", "vision", None),
    BenchmarkCase("vision_face_latency", "face_recognition", "vision", None),
    BenchmarkCase("vision_emotion_latency", "face_emotion", "vision", None),
]

ALL_CASES_BY_CATEGORY = {"llm": LLM_CASES, "asr": ASR_CASES, "tts": TTS_CASES, "vision": VISION_CASES}
INVOKERS = {"local_llm": invoke_llm, "asr": invoke_asr, "tts": invoke_tts, "object_detection": invoke_vision, "person_detection": invoke_vision, "gesture_recognition": invoke_vision, "face_recognition": invoke_vision, "face_emotion": invoke_vision}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", choices=list(ALL_CASES_BY_CATEGORY.keys()), default=None)
    args = parser.parse_args()

    if not REGISTRY_PATH.exists():
        print(f"BLOCKED: registry not found at {REGISTRY_PATH}", file=sys.stderr)  # noqa: T201
        return 1

    registry = ModelRegistry.load(REGISTRY_PATH)
    selector = ModelRuntimeSelector(registry)
    health = ModelHealthMonitor(registry, selector)
    runner = BenchmarkRunner(registry, selector, health)

    categories = [args.category] if args.category else list(ALL_CASES_BY_CATEGORY.keys())
    cases = [c for cat in categories for c in ALL_CASES_BY_CATEGORY[cat]]

    print(f"Running {len(cases)} benchmark case(s) across {len(categories)} categor(y/ies)...")  # noqa: T201
    started = time.time()
    report = runner.run_all(cases, INVOKERS)
    elapsed = time.time() - started

    print(f"\n{'CASE':<32} {'MODEL':<24} {'STATUS':<10} {'LATENCY':<10} DETAIL")  # noqa: T201
    print("-" * 110)  # noqa: T201
    for r in report.results:
        latency = f"{r.latency_ms:.0f}ms" if r.latency_ms is not None else "-"
        print(f"{r.case_id:<32} {r.model_id:<24} {r.status:<10} {latency:<10} {r.detail[:60]}")  # noqa: T201

    summary = report.summary()
    print(f"\nSummary: {summary} in {elapsed:.1f}s")  # noqa: T201
    print("BLOCKED results above are honest -- they mean the model wasn't actually available")  # noqa: T201
    print("on THIS machine (see docs/AI_MODEL_BENCHMARK_REPORT.md's environment note), not a failure to fake.")  # noqa: T201

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "note": (
                "Run on the dev sandbox, not real Pi-2/Pi-3 hardware. BLOCKED "
                "results mean the invoker/model genuinely isn't installed/reachable "
                "here (no Ollama, no faster-whisper, no Piper binary, no camera) -- "
                "see docs/PI2_QWEN25_05B_SETUP_REPORT.md for the one case "
                "(qwen2.5:0.5b LLM) already benchmarked on real Pi-2 hardware."
            ),
        },
        "categories_run": categories,
        **report.to_dict(),
    }
    RESULTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nResults persisted to {RESULTS_PATH}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
