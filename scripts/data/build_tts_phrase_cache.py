#!/usr/bin/env python3
"""scripts/data/build_tts_phrase_cache.py

Pre-renders the hospital phrase list to cached WAV files using the
already-deployed Piper voice model, per Phase 5's "use cached phrases and
selected voice models before training new TTS" recommendation.

Shells out to the `piper` executable directly (the same subprocess-mode
invocation bonbon_tts.backends.piper_tts.PiperTTS uses -- see that
module's docstring) rather than importing the ROS2 package, so this
script runs standalone without sourcing the ROS2 workspace. Honestly
reports BLOCKED if `piper` is not on PATH or the model file is missing,
per this repo's established hardware/tool-gating discipline (e.g.
scripts/ai_models/install_hailo_models.sh) -- never fabricates cached
audio it didn't actually render.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/hospital_phrase_list.yaml"))
    parser.add_argument("--model", type=Path, default=Path("models/piper/en_US-lessac-medium.onnx"))
    parser.add_argument("--out-dir", type=Path, default=Path("config/data/tts_phrase_cache"))
    args = parser.parse_args()

    piper_bin = shutil.which("piper")
    if piper_bin is None:
        print("Status: TOOLCHAIN_BLOCKED")
        print("`piper` executable not found on PATH -- cannot render cached phrases.")
        print("Install Piper (https://github.com/rhasspy/piper) and re-run.")
        return 1

    if not args.model.is_file():
        print(f"Status: MODEL_MISSING -- {args.model} does not exist.")
        return 1

    if not args.source.is_file():
        print(
            f"No phrase-list source at {args.source} -- nothing to cache. Honest current state: "
            "hospital operations has not yet supplied a reviewed phrase list to this repo "
            "(see dataset_registry.yaml's hospital_phrase_list entry, NEEDS_REVIEW).",
            file=sys.stderr,
        )
        return 0

    data = yaml.safe_load(args.source.read_text(encoding="utf-8")) or {}
    phrases = [p for p in data.get("phrases", []) if p.get("text")]
    if not phrases:
        print(f"{args.source} contained no usable phrases.")
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rendered = 0
    for i, entry in enumerate(phrases):
        text = entry["text"]
        phrase_id = entry.get("id", f"phrase_{i:04d}")
        out_wav = args.out_dir / f"{phrase_id}.wav"
        proc = subprocess.run(  # noqa: S603 -- piper_bin resolved via shutil.which, text is from a reviewed source file
            [piper_bin, "--model", str(args.model), "--output_file", str(out_wav)],
            input=text,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode != 0:
            print(f"FAILED to render {phrase_id!r}: {proc.stderr.strip()[:300]}", file=sys.stderr)
            continue
        rendered += 1

    print(f"Rendered {rendered}/{len(phrases)} phrases -> {args.out_dir}")
    print("Next: bonbon_data_pipeline.export_for_edge.EdgeDeploymentTracker.set_active('tts', ...)")
    return 0 if rendered == len(phrases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
