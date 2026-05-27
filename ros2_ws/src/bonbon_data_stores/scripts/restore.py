#!/usr/bin/env python3
"""CLI script: restore all BonBon data stores from a backup archive.

Usage
-----
    python restore.py <archive.tar.gz> [--data-dir /path/to/data]

WARNING
-------
This will OVERWRITE the current data directory.
Always create a fresh backup before restoring.
"""

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore BonBon data stores from a backup archive."
    )
    parser.add_argument(
        "archive",
        help="Path to the .tar.gz backup archive.",
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("BONBON_DATA_DIR", "/tmp/bonbon/data"),
        help="Root data directory to restore into (default: /tmp/bonbon/data)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    args = parser.parse_args()

    archive = Path(args.archive)
    data_dir = Path(args.data_dir)

    if not archive.exists():
        print(f"ERROR: archive not found: {archive}", file=sys.stderr)
        sys.exit(1)

    if not args.yes:
        answer = (
            input(
                f"This will OVERWRITE {data_dir}.\n"
                f"Restoring from: {archive}\n"
                "Continue? [y/N] "
            )
            .strip()
            .lower()
        )
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    from bonbon_data_stores.backup.backup_manager import BackupRestoreManager

    manager = BackupRestoreManager(
        db_path=data_dir / "bonbon_memory.db",
        faiss_index_dir=data_dir / "faiss_indexes",
        chroma_persist_dir=data_dir / "chromadb",
        backup_dir=data_dir.parent / "backups",
    )

    print(f"Restoring from {archive} …")
    results = manager.restore_backup(archive)

    for component, success in results.items():
        status = "✓" if success else "✗ FAILED"
        print(f"  {status}  {component}")

    if all(results.values()):
        print("Restore complete.")
    else:
        print("Restore completed with errors.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
