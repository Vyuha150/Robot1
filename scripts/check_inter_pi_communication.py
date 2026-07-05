#!/usr/bin/env python3
"""Inter-Pi communication check entry point (canonical interface in scripts/).

Delegates unchanged to devops/scripts/check_inter_pi_communication.py,
matching this repo's scripts/ -> devops/scripts/ delegation convention.

Usage:
    python3 scripts/check_inter_pi_communication.py --role pi1
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEVOPS = _ROOT / "devops" / "scripts" / "check_inter_pi_communication.py"


def main(argv: list[str] | None = None) -> int:
    if not _DEVOPS.exists():
        print(f"check script not found: {_DEVOPS}", file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, str(_DEVOPS), *(argv or sys.argv[1:])])


if __name__ == "__main__":
    raise SystemExit(main())
