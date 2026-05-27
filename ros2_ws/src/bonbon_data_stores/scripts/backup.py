#!/usr/bin/env python3
"""CLI script: create a manual backup of all BonBon data stores.

Usage
-----
    python backup.py [--data-dir /path/to/data] [--backup-dir /path/to/backups] [--label my_label]

Environment variables
---------------------
    BONBON_DATA_DIR   — overrides --data-dir
"""

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a backup of all BonBon data stores.")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("BONBON_DATA_DIR", "/tmp/bonbon/data"),
        help="Root data directory (default: /tmp/bonbon/data or $BONBON_DATA_DIR)",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help="Backup output directory (default: <data-dir>/../backups)",
    )
    parser.add_argument(
        "--label",
        default="manual",
        help="Label appended to the archive filename (default: manual)",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Disable gzip compression",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    backup_dir = Path(args.backup_dir) if args.backup_dir else data_dir.parent / "backups"

    # Import here so the script can be used stand-alone
    from bonbon_data_stores.backup.backup_manager import BackupRestoreManager

    manager = BackupRestoreManager(
        db_path=data_dir / "bonbon_memory.db",
        faiss_index_dir=data_dir / "faiss_indexes",
        chroma_persist_dir=data_dir / "chromadb",
        backup_dir=backup_dir,
        compress=not args.no_compress,
    )

    print(f"Creating backup from {data_dir} → {backup_dir} …")
    archive = manager.create_backup(label=args.label)
    print(f"✓ Backup created: {archive}")


if __name__ == "__main__":
    main()
