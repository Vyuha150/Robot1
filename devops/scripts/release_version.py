#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate BonBon release version metadata.")
    parser.add_argument("--channel", default=os.getenv("BONBON_RELEASE_CHANNEL", "dev"))
    parser.add_argument("--output", default="deployment/ota/release_metadata.env")
    parser.add_argument("--artifact", action="append", default=[])
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    git_sha = _git(root, "rev-parse", "--short=12", "HEAD") or "unknown"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    version = f"{args.channel}-{timestamp}-{git_sha}"
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"BONBON_VERSION={version}", f"BONBON_GIT_SHA={git_sha}", f"BONBON_RELEASE_CHANNEL={args.channel}"]
    for artifact in args.artifact:
        artifact_path = root / artifact
        if artifact_path.exists():
            lines.append(f"SHA256_{artifact_path.name.replace('.', '_').upper()}={_sha256(artifact_path)}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(version)
    return 0


def _git(root: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
