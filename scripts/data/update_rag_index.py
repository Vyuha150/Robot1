#!/usr/bin/env python3
"""scripts/data/update_rag_index.py

Rebuilds the hospital-knowledge RAG index (SQLite exact-match FAQ table +
JSONL document index) from hospital-approved source documents, per Phase 5's
"improve RAG by improving structured hospital data first" recommendation.

Reads YAML/JSON files from an input directory in one of two shapes:
  - FAQ shape:      {"faqs": [{"question": ..., "answer": ..., ...}]}
  - Document shape: {"documents": [{"text": ..., "metadata": {...}}]}

Writes a NEW timestamped index file rather than overwriting the previous
one in place -- config/data/training_targets.yaml's rollback_plan for
hospital_knowledge_rag depends on the previous file still existing.

Does NOT modify bonbon_llm.core.rag_retriever.RAGRetriever's in-memory
state directly -- that module has no file-based load hook today (it is
seeded in-code via `_seed_defaults()`). This script produces the on-disk
artifact; wiring RAGRetriever to load it at boot is a follow-up
integration task, stated here rather than silently assumed done (see
docs/EDGE_MODEL_EXPORT_REPORT.md).

Honest by construction: with no input documents present (this repo's
actual current state -- see dataset_registry.yaml's hospital_approved_documents
entry, NEEDS_REVIEW), this script reports zero documents indexed rather
than fabricating placeholder content.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import yaml


def _load_source_files(input_dir: Path) -> tuple[list[dict], list[dict]]:
    faqs: list[dict] = []
    documents: list[dict] = []
    if not input_dir.is_dir():
        return faqs, documents
    for path in sorted(input_dir.glob("**/*")):
        if path.suffix.lower() not in (".yaml", ".yml", ".json"):
            continue
        try:
            if path.suffix.lower() == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            print(f"WARNING: skipping unreadable source file {path}: {exc}", file=sys.stderr)
            continue
        if not isinstance(data, dict):
            continue
        for faq in data.get("faqs", []):
            if "question" in faq and "answer" in faq:
                faqs.append(faq)
        for doc in data.get("documents", []):
            if "text" in doc:
                documents.append(doc)
    return faqs, documents


def build_index(input_dir: Path, out_dir: Path) -> Path:
    faqs, documents = _load_source_files(input_dir)

    out_dir.mkdir(parents=True, exist_ok=True)
    version_tag = time.strftime("%Y%m%d_%H%M%S")
    sqlite_path = out_dir / f"rag_index_{version_tag}.sqlite"
    jsonl_path = out_dir / f"rag_index_{version_tag}.jsonl"

    conn = sqlite3.connect(sqlite_path)
    conn.execute(
        "CREATE TABLE faq_exact_match (question TEXT PRIMARY KEY, answer TEXT NOT NULL, source_file TEXT)"
    )
    for faq in faqs:
        conn.execute(
            "INSERT OR REPLACE INTO faq_exact_match (question, answer, source_file) VALUES (?, ?, ?)",
            (faq["question"], faq["answer"], faq.get("_source_file", "")),
        )
    conn.commit()
    conn.close()

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for doc in documents:
            f.write(json.dumps(doc) + "\n")
        for faq in faqs:
            # FAQ answers are also embeddable documents, matching
            # bonbon_llm.core.rag_retriever.RAGRetriever.add_faq_document's
            # convention (question stored as metadata, answer as text).
            f.write(json.dumps({"text": faq["answer"], "metadata": {"question": faq["question"], "type": "faq"}}) + "\n")

    return sqlite_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=Path("data/hospital_knowledge_source"))
    parser.add_argument("--out-dir", type=Path, default=Path("config/data/rag_index"))
    args = parser.parse_args()

    faqs, documents = _load_source_files(args.input_dir)
    if not faqs and not documents:
        print(
            f"No source documents found in {args.input_dir} -- nothing to index. "
            "This is the honest current state (see dataset_registry.yaml's "
            "hospital_approved_documents/hospital_faq_table entries, both NEEDS_REVIEW): "
            "no partner hospital document set has been supplied to this repo yet."
        )
        return 0

    sqlite_path = build_index(args.input_dir, args.out_dir)
    print(f"Indexed {len(faqs)} FAQ entries and {len(documents)} documents -> {sqlite_path}")
    print("Next: wire RAGRetriever to load this index at boot (not yet done -- see EDGE_MODEL_EXPORT_REPORT.md),")
    print("then bonbon_data_pipeline.export_for_edge.EdgeDeploymentTracker.set_active('hospital_knowledge_rag', ...).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
