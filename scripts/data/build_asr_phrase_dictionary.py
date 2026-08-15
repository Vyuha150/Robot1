#!/usr/bin/env python3
"""scripts/data/build_asr_phrase_dictionary.py

Builds an ASR vocabulary/phrase-boost dictionary from the hospital phrase
list (dataset_registry.yaml's `hospital_phrase_list` entry), per Phase 5's
"improve ASR with phrase correction and vocabulary before full fine-tuning"
recommendation.

Reads a YAML source file shaped {"phrases": [{"text": ..., "language": ...}]}
and writes one hotword-list file per language, in the plain newline-
separated format faster-whisper's `hotwords`/`initial_prompt` parameters
accept.

Honest gap, stated plainly: bonbon_speech_ai's ASR call does not currently
pass hotwords/initial_prompt to faster-whisper (confirmed: no
hotword/initial_prompt/vocabulary_boost reference anywhere in
ros2_ws/src/bonbon_speech_ai). This script produces the dictionary file;
wiring it into the actual transcribe() call is a follow-up integration
task, not done by this script.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import yaml


def build_dictionaries(source_path: Path, out_dir: Path) -> dict[str, int]:
    if not source_path.is_file():
        return {}
    data = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    phrases = data.get("phrases", [])

    by_language: dict[str, list[str]] = defaultdict(list)
    for entry in phrases:
        text = entry.get("text")
        language = entry.get("language", "unknown")
        if text:
            by_language[language].append(text)

    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for language, texts in by_language.items():
        out_path = out_dir / f"asr_phrases_{language}.txt"
        out_path.write_text("\n".join(texts) + "\n", encoding="utf-8")
        counts[language] = len(texts)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/hospital_phrase_list.yaml"))
    parser.add_argument("--out-dir", type=Path, default=Path("config/data/asr_phrase_dictionaries"))
    args = parser.parse_args()

    if not args.source.is_file():
        print(
            f"No phrase-list source at {args.source} -- nothing to build. This is the honest "
            "current state (dataset_registry.yaml's hospital_phrase_list entry is NEEDS_REVIEW: "
            "hospital operations has not yet supplied a reviewed phrase list to this repo).",
            file=sys.stderr,
        )
        return 0

    counts = build_dictionaries(args.source, args.out_dir)
    if not counts:
        print(f"{args.source} contained no usable phrases.")
        return 0

    for language, n in counts.items():
        print(f"{language}: {n} phrases -> {args.out_dir / f'asr_phrases_{language}.txt'}")
    print("\nNext (not done by this script): pass the relevant language file's contents as "
          "faster-whisper's `hotwords` parameter in bonbon_speech_ai's transcribe() call.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
