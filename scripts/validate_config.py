#!/usr/bin/env python3
"""Config validation entry point (canonical interface in scripts/).

Wraps the deployment validator in devops/scripts/validate_config.py, adding an
``--all`` mode that validates every supported deployment environment in one go
(used by CI). Single-environment validation delegates unchanged.

Usage:
    python scripts/validate_config.py --all
    python scripts/validate_config.py --env production_robot
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DEVOPS = _ROOT / "devops" / "scripts" / "validate_config.py"

# Must match REQUIRED_ENVS in devops/scripts/validate_config.py.
_ENVS = ["local_dev", "simulation", "lab_robot", "staging_robot", "production_robot"]


def _validate(env: str, extra: list[str]) -> int:
    cmd = [sys.executable, str(_DEVOPS), "--env", env, *extra]
    print(f"==> validate_config --env {env}")
    return subprocess.call(cmd)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate BonBon deployment config.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="validate every environment")
    group.add_argument("--env", choices=_ENVS, help="validate a single environment")
    parser.add_argument("--require-runtime-secrets", action="store_true")
    args, _unknown = parser.parse_known_args(argv)

    extra = ["--require-runtime-secrets"] if args.require_runtime_secrets else []

    if not _DEVOPS.exists():
        print(f"validator not found: {_DEVOPS}", file=sys.stderr)
        return 2

    if args.all:
        failed = [e for e in _ENVS if _validate(e, extra) != 0]
        if failed:
            print(f"config validation FAILED for: {', '.join(failed)}", file=sys.stderr)
            return 1
        print("config validation OK for all environments")
        return 0
    return _validate(args.env, extra)


if __name__ == "__main__":
    raise SystemExit(main())
