#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a BonBon release artifact checksum.")
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()

    artifact = Path(args.artifact)
    checksum_file = Path(args.sha256)
    if not artifact.exists():
        print(f"ERROR: release artifact missing: {artifact}", file=sys.stderr)
        return 1
    if not checksum_file.exists():
        print(f"ERROR: checksum file missing: {checksum_file}", file=sys.stderr)
        return 1

    expected = checksum_file.read_text(encoding="utf-8").split()[0].strip()
    actual = _sha256(artifact)
    if actual != expected:
        print(f"ERROR: checksum mismatch for {artifact}: expected {expected}, got {actual}", file=sys.stderr)
        return 1
    print(f"Checksum verified: {artifact}")
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
