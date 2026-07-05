#!/usr/bin/env python3
"""Network bootstrap entry point (canonical interface in scripts/).

Delegates unchanged to devops/scripts/bootstrap_pi_network.py, matching
this repo's scripts/ -> devops/scripts/ delegation convention (see
scripts/validate_config.py for the same pattern applied to config
validation).

Usage:
    sudo python3 scripts/bootstrap_pi_network.py --role pi2 --apply
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEVOPS = _ROOT / "devops" / "scripts" / "bootstrap_pi_network.py"


def main(argv: list[str] | None = None) -> int:
    if not _DEVOPS.exists():
        print(f"bootstrap script not found: {_DEVOPS}", file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, str(_DEVOPS), *(argv or sys.argv[1:])])


if __name__ == "__main__":
    raise SystemExit(main())
