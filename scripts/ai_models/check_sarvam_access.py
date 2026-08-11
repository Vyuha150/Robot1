#!/usr/bin/env python3
"""check_sarvam_access.py — honestly detects whether Sarvam AI's Edge
package or API access exists in this environment. Never invents a
download URL or assumes access. Mirrors the detection logic in
bonbon_sarvam_adapter.sarvam_capability_detector (Phase 5) so this CLI
and the runtime dashboard check always agree -- this script imports that
module when it's importable, and falls back to the same inline checks
if run standalone (e.g. before bonbon_sarvam_adapter is built/installed
on a given machine).

Usage:
    python3 scripts/ai_models/check_sarvam_access.py
    python3 scripts/ai_models/check_sarvam_access.py --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys


def _inline_detect() -> dict:
    edge_installed = importlib.util.find_spec("sarvam") is not None or importlib.util.find_spec("sarvam_edge") is not None
    api_key = os.environ.get("SARVAM_API_KEY", "")
    cloud_enabled = os.environ.get("BONBON_CLOUD_ENABLED", "false").lower() == "true"

    if edge_installed:
        mode = "edge"
        available = True
        reason = "sarvam/sarvam_edge Python package is importable"
    elif api_key and cloud_enabled:
        mode = "api"
        available = True
        reason = "SARVAM_API_KEY is set and BONBON_CLOUD_ENABLED=true"
    elif api_key and not cloud_enabled:
        mode = "unavailable"
        available = False
        reason = "SARVAM_API_KEY is set, but BONBON_CLOUD_ENABLED is not true -- rule 4: never use cloud API by default"
    else:
        mode = "unavailable"
        available = False
        reason = "no Sarvam Edge package installed and no SARVAM_API_KEY set -- zero prior Sarvam integration found in this repo"

    return {
        "available": available,
        "mode": mode,
        "reason": reason,
        "languagesSupported": ["en", "hi", "te"] if available else [],
        "fallbackActive": not available,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        from bonbon_sarvam_adapter.sarvam_capability_detector import detect_sarvam_capabilities  # type: ignore[import-not-found]

        result = detect_sarvam_capabilities()
        result_dict = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    except ImportError:
        result_dict = _inline_detect()

    if args.json:
        print(json.dumps(result_dict, indent=2))  # noqa: T201
    else:
        print(f"Sarvam available: {result_dict['available']}")  # noqa: T201
        print(f"Mode:              {result_dict['mode']}")  # noqa: T201
        print(f"Reason:            {result_dict['reason']}")  # noqa: T201
        print(f"Languages:         {result_dict.get('languagesSupported', [])}")  # noqa: T201
        print(f"Fallback active:   {result_dict.get('fallbackActive', True)}")  # noqa: T201

    return 0 if result_dict["available"] else 1


if __name__ == "__main__":
    sys.exit(main())
