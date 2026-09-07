"""
ingest_all.py — Script to ingest all documents in data/documents/ into ChromaDB + BM25.
"""

import sys
import os
from pathlib import Path
from datetime import date

# Ensure we can import from src/
sys.path.insert(0, str(Path(__file__).parent))

from src.ingestion.pipeline import ingest_document
from src.ingestion.metadata import Regulator, DocType
from src.retrieval.vector_store import VectorStore
from src.retrieval.bm25_index import BM25Index

import json

# Document manifest: each document we want to ingest.
#
# NOTE: every file below is SYNTHETIC — representative regulatory text
# written to evaluate this pipeline, not a verbatim instrument. Titles
# therefore describe subject matter and do not assert a circular number,
# and each source_url points at the regulator's real landing page for that
# subject area rather than at a specific instrument.
# See data/documents/README.md.
DOCUMENTS = [
    {
        "file": "data/documents/cbuae_decree_law_6_2025_sample.txt",
        "title": "CBUAE Federal Decree-Law No. 6 of 2025 (synthetic extract)",
        "regulator": Regulator.CBUAE,
        "doc_type": DocType.FEDERAL_LAW,
        "source_url": "https://uaelegislation.gov.ae/en/legislations/3284",
        "effective_date": date(2025, 1, 1),
    },
    {
        "file": "data/documents/vara_rulebook_vasps_2025.txt",
        "title": "VARA VASP Rulebook excerpts (synthetic)",
        "regulator": Regulator.VARA,
        "doc_type": DocType.RULEBOOK,
        "source_url": "https://rulebooks.vara.ae/",
        "effective_date": date(2025, 3, 1),
    },
    {
        "file": "data/documents/cbuae_aml_circular_3_2025.txt",
        "title": "CBUAE AML/CFT Requirements for LFIs (synthetic)",
        "regulator": Regulator.CBUAE,
        "doc_type": DocType.CIRCULAR,
        "source_url": "https://rulebook.centralbank.ae/en/rulebook/amlcft",
        "effective_date": date(2025, 2, 15),
    },
    {
        "file": "data/documents/cbuae_consumer_protection_reg_2025.txt",
        "title": "CBUAE Consumer Protection Requirements (synthetic)",
        "regulator": Regulator.CBUAE,
        "doc_type": DocType.REGULATION,
        "source_url": "https://rulebook.centralbank.ae/en/rulebook/consumer-protection-regulation",
        "effective_date": date(2025, 1, 15),
    },
    {
        "file": "data/documents/vara_compliance_risk_mgmt_2025.txt",
        "title": "VARA Compliance and Risk Management (synthetic)",
        "regulator": Regulator.VARA,
        "doc_type": DocType.REGULATION,
        "source_url": "https://rulebooks.vara.ae/",
        "effective_date": date(2025, 4, 1),
    },
]


def main():
    print("=" * 60)
    print("UAE Regulatory Compliance RAG — Full Ingestion")
    print("=" * 60)

    # Step 1: Ingest all documents through the pipeline (produces JSON chunks)
    all_chunk_records = []
    for doc_info in DOCUMENTS:
        filepath = Path(doc_info["file"])
        if not filepath.exists():
            print(f"  [SKIP] {filepath} not found.")
            continue

        print(f"\n  Ingesting: {doc_info['title']}")
        result = ingest_document(
            file_path=filepath,
            title=doc_info["title"],
            regulator=doc_info["regulator"],
            doc_type=doc_info["doc_type"],
            source_url=doc_info["source_url"],
            effective_date=doc_info["effective_date"],
        )

        if result.success:
            print(f"    OK: {result.chunk_count} chunks, {result.total_tokens} tokens")
            # Load the generated JSON to get the chunk records
            if result.output_path:
                with open(result.output_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    all_chunk_records.extend(data["chunks"])
        else:
            print(f"    FAIL: {result.error}")

    if not all_chunk_records:
        print("\nNo chunks to index. Exiting.")
        return

    # Step 2: Contextual enrichment — prepend doc metadata to chunk text.
    # This helps the dense embedding model distinguish chunks from different
    # documents and sections, dramatically improving retrieval precision.
    # We enrich a COPY of the text for the vector store; the original text
    # is preserved for citation verification (exact quote matching).
    enriched_records = []
    for chunk in all_chunk_records:
        enriched = dict(chunk)  # shallow copy
        meta = chunk.get("metadata", {})
        prefix_parts = []
        if meta.get("regulator"):
            prefix_parts.append(meta["regulator"])
        if meta.get("doc_title"):
            prefix_parts.append(meta["doc_title"])
        if meta.get("section_heading"):
            prefix_parts.append(meta["section_heading"])
        if prefix_parts:
            prefix = "[" + " | ".join(prefix_parts) + "] "
            enriched["text"] = prefix + chunk["text"]
        enriched_records.append(enriched)

    print(f"  Applied contextual enrichment to {len(enriched_records)} chunks.")

    # Step 3: Index enriched text into ChromaDB (dense)
    print(f"\n  Indexing {len(enriched_records)} enriched chunks into ChromaDB...")
    vs = VectorStore()
    vs.add_chunks(enriched_records)
    print(f"    ChromaDB count: {vs.get_document_count()} chunks")

    # Step 4: Index raw text into BM25 (sparse) — no enrichment needed
    # BM25 keyword search benefits from raw text without metadata prefixes.
    print(f"  Building BM25 index from raw text...")
    bm25 = BM25Index()
    bm25.build_index(all_chunk_records)
    bm25.save()
    print(f"    BM25 count: {bm25.get_document_count()} chunks")

    print("\n" + "=" * 60)
    print("Ingestion complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
