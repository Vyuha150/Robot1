#!/usr/bin/env python3
"""Load hospital_kb/*.md into bonbon_llm's RAGRetriever.

Deployment-time tool, not part of the running kiosk API — see
hospital_kb/README.md for why this is a separate, manually-run step.

Usage:
    python scripts/seed_hospital_kb.py [--persist-dir /var/bonbon/knowledge]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_KB_DIR = Path(__file__).parent.parent / "hospital_kb"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persist-dir", default="", help="ChromaDB persistence directory")
    parser.add_argument("--backend", default="chroma", choices=["chroma", "faiss", "numpy"])
    args = parser.parse_args()

    try:
        from bonbon_llm.core.rag_retriever import RAGRetriever
    except ImportError:
        print(
            "bonbon_llm is not importable in this environment — install/activate "
            "the bonbon_llm package first (this script must run where bonbon_llm "
            "is on PYTHONPATH, e.g. after `colcon build` + sourcing the workspace).",
            file=sys.stderr,
        )
        return 1

    rag = RAGRetriever(backend=args.backend, persist_dir=args.persist_dir or None)

    doc_files = sorted(_KB_DIR.glob("*.md"))
    if not doc_files:
        print(f"No .md files found in {_KB_DIR}", file=sys.stderr)
        return 1

    for path in doc_files:
        if path.name == "README.md":
            continue
        text = path.read_text(encoding="utf-8")
        rag.add_document(text, metadata={"category": path.stem, "source": str(path.name)})
        print(f"Seeded: {path.name}")

    print(f"Done — seeded {len(doc_files) - 1} hospital knowledge document(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
