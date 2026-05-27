"""BackupRestoreManager — consistent snapshot of all data stores.

Backup strategy
---------------
1. **SQLite** — uses the sqlite3 ``.backup()`` API (online, consistent).
2. **FAISS indexes** — copies ``*.index`` and ``*.json`` sidecar files.
3. **ChromaDB** — copies the entire persist directory.
4. The three artefacts are bundled into a timestamped ``.tar.gz`` archive.
5. Old archives beyond ``max_backups`` are automatically pruned.

Restore
-------
1. Extract the archive into a temp directory.
2. Restore SQLite via ``.backup()`` (reverse direction).
3. Overwrite FAISS index files.
4. Overwrite ChromaDB persist directory.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import tarfile
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class BackupRestoreManager:
    """Create and restore consistent snapshots of all BonBon data stores.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    faiss_index_dir:
        Directory containing FAISS ``.index`` / ``.json`` files.
    chroma_persist_dir:
        ChromaDB persistence directory.
    backup_dir:
        Root directory where archives are stored.
    max_backups:
        Rolling window; older archives are pruned after each new backup.
    compress:
        GZip-compress the archive (default True).
    """

    def __init__(
        self,
        db_path: Path,
        faiss_index_dir: Path,
        chroma_persist_dir: Path,
        backup_dir: Path,
        max_backups: int = 7,
        compress: bool = True,
    ) -> None:
        self._db_path = Path(db_path)
        self._faiss_dir = Path(faiss_index_dir)
        self._chroma_dir = Path(chroma_persist_dir)
        self._backup_dir = Path(backup_dir)
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._max_backups = max_backups
        self._compress = compress

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def create_backup(self, label: str = "") -> Path:
        """Create a timestamped backup archive.

        Returns
        -------
        Path to the created archive.
        """
        ts = time.strftime("%Y%m%dT%H%M%S")
        slug = f"bonbon_backup_{ts}"
        if label:
            slug += f"_{label}"
        ext = ".tar.gz" if self._compress else ".tar"
        archive_path = self._backup_dir / (slug + ext)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # 1. SQLite backup
            self._backup_sqlite(tmp_path / "bonbon_memory.db")

            # 2. FAISS indexes
            faiss_dst = tmp_path / "faiss_indexes"
            if self._faiss_dir.exists():
                shutil.copytree(str(self._faiss_dir), str(faiss_dst))
            else:
                faiss_dst.mkdir()

            # 3. ChromaDB
            chroma_dst = tmp_path / "chromadb"
            if self._chroma_dir.exists():
                shutil.copytree(str(self._chroma_dir), str(chroma_dst))
            else:
                chroma_dst.mkdir()

            # 4. Bundle into archive
            mode = "w:gz" if self._compress else "w"
            with tarfile.open(str(archive_path), mode) as tar:
                tar.add(str(tmp_path), arcname=".")

        logger.info("Backup created: %s", archive_path)
        self._prune_old_backups()
        return archive_path

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore_backup(self, archive_path: Path) -> dict[str, bool]:
        """Restore from a backup archive.

        Returns a dict ``{ 'sqlite': bool, 'faiss': bool, 'chroma': bool }``
        indicating which components were restored successfully.
        """
        archive_path = Path(archive_path)
        if not archive_path.exists():
            raise FileNotFoundError(f"Backup archive not found: {archive_path}")

        results = {"sqlite": False, "faiss": False, "chroma": False}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Extract
            mode = "r:gz" if str(archive_path).endswith(".gz") else "r"
            with tarfile.open(str(archive_path), mode) as tar:
                tar.extractall(str(tmp_path))

            # 1. SQLite
            src_db = tmp_path / "bonbon_memory.db"
            if src_db.exists():
                try:
                    self._restore_sqlite(src_db)
                    results["sqlite"] = True
                except Exception as exc:
                    logger.error("SQLite restore failed: %s", exc)

            # 2. FAISS
            src_faiss = tmp_path / "faiss_indexes"
            if src_faiss.exists():
                try:
                    if self._faiss_dir.exists():
                        shutil.rmtree(str(self._faiss_dir))
                    shutil.copytree(str(src_faiss), str(self._faiss_dir))
                    results["faiss"] = True
                except Exception as exc:
                    logger.error("FAISS restore failed: %s", exc)

            # 3. ChromaDB
            src_chroma = tmp_path / "chromadb"
            if src_chroma.exists():
                try:
                    if self._chroma_dir.exists():
                        shutil.rmtree(str(self._chroma_dir))
                    shutil.copytree(str(src_chroma), str(self._chroma_dir))
                    results["chroma"] = True
                except Exception as exc:
                    logger.error("ChromaDB restore failed: %s", exc)

        logger.info("Restore complete from %s: %s", archive_path, results)
        return results

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def list_backups(self) -> list[tuple[Path, float, int]]:
        """Return ``[(path, mtime, size_bytes), ...]`` sorted newest first."""
        archives = sorted(
            [
                p
                for p in self._backup_dir.iterdir()
                if p.suffix in (".gz", ".tar") or p.name.endswith(".tar.gz")
            ],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return [(p, p.stat().st_mtime, p.stat().st_size) for p in archives]

    def latest_backup(self) -> Path | None:
        backups = self.list_backups()
        return backups[0][0] if backups else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _backup_sqlite(self, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        src_conn = sqlite3.connect(str(self._db_path))
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()
        logger.debug("SQLite backup written to %s", dst)

    def _restore_sqlite(self, src: Path) -> None:
        src_conn = sqlite3.connect(str(src))
        dst_conn = sqlite3.connect(str(self._db_path))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()
        logger.debug("SQLite restored from %s", src)

    def _prune_old_backups(self) -> None:
        backups = self.list_backups()
        for path, _, _ in backups[self._max_backups :]:
            try:
                path.unlink()
                logger.debug("Pruned old backup: %s", path)
            except Exception as exc:
                logger.warning("Failed to prune backup %s: %s", path, exc)
