#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REQUIRED_ENVS = {
    "local_dev": ["BONBON_ENV"],
    "simulation": ["BONBON_ENV"],
    "lab_robot": ["BONBON_ENV", "BONBON_ROBOT_HOST", "BONBON_ROBOT_USER"],
    "staging_robot": ["BONBON_ENV", "BONBON_ROBOT_HOST", "BONBON_ROBOT_USER"],
    "production_robot": ["BONBON_ENV", "BONBON_ROBOT_HOST", "BONBON_ROBOT_USER", "BONBON_RELEASE_CHANNEL"],
}

REQUIRED_CONFIG_FILES = ["runtime.env", "services.yaml"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate BonBon deployment config.")
    parser.add_argument("--env", required=True, choices=sorted(REQUIRED_ENVS))
    parser.add_argument("--root", default=Path(__file__).resolve().parents[2])
    parser.add_argument("--require-runtime-secrets", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    config_dir = root / "devops" / "config" / args.env
    errors: list[str] = []
    if not config_dir.exists():
        errors.append(f"missing config directory: {config_dir}")

    for filename in REQUIRED_CONFIG_FILES:
        if not (config_dir / filename).exists():
            errors.append(f"missing config file: {config_dir / filename}")

    env_values = _load_env_file(config_dir / "runtime.env")
    merged = {**env_values, **{key: value for key, value in os.environ.items() if value}}
    for key in REQUIRED_ENVS[args.env]:
        if not merged.get(key):
            errors.append(f"missing environment variable: {key}")

    if args.require_runtime_secrets:
        for key in ("BONBON_JWT_SECRET", "BONBON_ADMIN_PASSWORD"):
            if not merged.get(key):
                errors.append(f"missing runtime secret: {key}")

    model_manifest = config_dir / "models.manifest"
    if model_manifest.exists():
        for raw in model_manifest.read_text(encoding="utf-8").splitlines():
            item = raw.strip()
            if item and not item.startswith("#") and not (root / item).exists():
                errors.append(f"missing model file: {item}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Config validation passed for {args.env}")
    return 0


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


if __name__ == "__main__":
    raise SystemExit(main())
