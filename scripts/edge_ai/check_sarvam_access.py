#!/usr/bin/env python3
"""Sarvam access check entry point (Edge AI Runtime brief, Phase 11).

Delegates unchanged to scripts/ai_models/check_sarvam_access.py, which
already honestly detects Sarvam Edge/API availability (never invents a
download URL, never assumes access) -- see
docs/DUPLICATE_PIPELINE_AUDIT.md for why this doesn't reimplement that
detection logic.

Usage:
    python3 scripts/edge_ai/check_sarvam_access.py
    python3 scripts/edge_ai/check_sarvam_access.py --json
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_TARGET = _ROOT / "scripts" / "ai_models" / "check_sarvam_access.py"


def main(argv: list[str] | None = None) -> int:
    if not _TARGET.exists():
        print(f"check script not found: {_TARGET}", file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, str(_TARGET), *(argv or sys.argv[1:])])


if __name__ == "__main__":
    raise SystemExit(main())
