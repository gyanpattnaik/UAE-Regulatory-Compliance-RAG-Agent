"""
pipeline.py — Ingestion orchestrator: parse → chunk → validate → persist.

This is the main entry point for adding a document to the knowledge base.
It orchestrates: parser → chunker → metadata validation → JSON persistence.

Embedding (ChromaDB storage) is handled in Build Step 2. This pipeline
outputs validated JSON chunks ready for embedding.
"""

from __future__ import annotations

import json
import re
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .chunker import chunk_document, TextChunk
from .metadata import (
    ChunkMetadata,
    DocumentMetadata,
    DocType,
    LanguageAuthority,
    Regulator,
)
from .parser import parse_document, ParsedDocument

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths from environment (with sensible defaults)
# ---------------------------------------------------------------------------

_PROCESSED_DIR = Path(os.getenv("PROCESSED_DIR", "./data/processed"))
_LOGS_DIR = Path(os.getenv("INGESTION_LOGS_DIR", "./data/ingestion_logs"))
_MAX_CHUNK_TOKENS = int(os.getenv("MAX_CHUNK_TOKENS", "800"))
_CHUNK_OVERLAP_TOKENS = int(os.getenv("CHUNK_OVERLAP_TOKENS", "150"))


# ---------------------------------------------------------------------------
# Result data structures
# ---------------------------------------------------------------------------

@dataclass
class IngestResult:
    """
    Result of a single document ingestion run.
    This is what the CLI and tests inspect.
    """
    success: bool
    doc_id: str
    file_path: str
    title: str
    regulator: str
    doc_type: str
    chunk_count: int = 0
    total_tokens: int = 0
    page_count: int = 0
    parse_warnings: list[str] = field(default_factory=list)
    chunk_warnings: list[str] = field(default_factory=list)
    output_path: Optional[str] = None
    error: Optional[str] = None
    ingested_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core ingestion function
# ---------------------------------------------------------------------------

def ingest_document(
    file_path: Path,
    title: str,
    regulator: Regulator,
    doc_type: DocType,
    source_url: str,
    effective_date: Optional[date] = None,
    language_authority: LanguageAuthority = LanguageAuthority.EN_TRANSLATION,
    in_force: bool = True,
    supersedes: Optional[str] = None,
    processed_dir: Optional[Path] = None,
    logs_dir: Optional[Path] = None,
    max_tokens: int = _MAX_CHUNK_TOKENS,
    overlap_tokens: int = _CHUNK_OVERLAP_TOKENS,
) -> IngestResult:
    """
    Ingest a single regulatory document into the knowledge base.

    Steps:
    1. Parse document (PDF or text)
    2. Validate + build DocumentMetadata
    3. Chunk document (structure-aware)
    4. Attach ChunkMetadata to each chunk
    5. Persist chunks as JSON to processed_dir
    6. Write ingestion audit log

    Args:
        file_path: Path to the document file.
        title: Official document title.
        regulator: Issuing regulatory body (Regulator enum).
        doc_type: Document type (DocType enum).
        source_url: Public URL of the document.
        effective_date: Date the regulation came into force.
        language_authority: Language authority of the document.
        in_force: Whether the document is currently in force.
        supersedes: doc_id of the document this supersedes (if any).
        processed_dir: Output directory for chunk JSON files.
        logs_dir: Directory for ingestion audit logs.
        max_tokens: Max tokens per chunk.
        overlap_tokens: Token overlap between chunks.

    Returns:
        IngestResult with full summary.
    """
    processed_dir = processed_dir or _PROCESSED_DIR
    logs_dir = logs_dir or _LOGS_DIR
    processed_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    file_path = Path(file_path)

    # ------------------------------------------------------------------
    # Step 1: Parse
    # ------------------------------------------------------------------
    try:
        logger.info(f"Parsing: {file_path.name}")
        parsed: ParsedDocument = parse_document(file_path)
    except Exception as e:
        error_msg = f"Parse failed: {e}"
        logger.error(error_msg)
        result = IngestResult(
            success=False,
            doc_id="",
            file_path=str(file_path),
            title=title,
            regulator=regulator.value,
            doc_type=doc_type.value,
            error=error_msg,
        )
        _write_log(result, logs_dir)
        return result

    # ------------------------------------------------------------------
    # Step 2: Build DocumentMetadata
    # ------------------------------------------------------------------
    doc_id = DocumentMetadata.generate_doc_id(source_url, parsed.checksum)

    try:
        doc_meta = DocumentMetadata(
            doc_id=doc_id,
            title=title,
            regulator=regulator,
            doc_type=doc_type,
            source_url=source_url,
            checksum=parsed.checksum,
            effective_date=effective_date,
            language_authority=language_authority,
            in_force=in_force,
            supersedes=supersedes,
        )
    except Exception as e:
        error_msg = f"Metadata validation failed: {e}"
        logger.error(error_msg)
        result = IngestResult(
            success=False,
            doc_id=doc_id,
            file_path=str(file_path),
            title=title,
            regulator=regulator.value,
            doc_type=doc_type.value,
            error=error_msg,
            parse_warnings=parsed.parse_warnings,
        )
        _write_log(result, logs_dir)
        return result

    # ------------------------------------------------------------------
    # Step 3: Chunk
    # ------------------------------------------------------------------
    logger.info(f"Chunking: {len(parsed.raw_text)} chars, {parsed.page_count} pages")
    chunk_result = chunk_document(parsed, max_tokens=max_tokens, overlap_tokens=overlap_tokens)

    if not chunk_result.chunks:
        error_msg = "Chunking produced 0 chunks — document may be empty or unparseable."
        result = IngestResult(
            success=False,
            doc_id=doc_id,
            file_path=str(file_path),
            title=title,
            regulator=regulator.value,
            doc_type=doc_type.value,
            parse_warnings=parsed.parse_warnings,
            chunk_warnings=chunk_result.warnings,
            error=error_msg,
        )
        _write_log(result, logs_dir)
        return result

    # ------------------------------------------------------------------
    # Step 4: Attach ChunkMetadata + build output records
    # ------------------------------------------------------------------
    total_chunks = len(chunk_result.chunks)
    chunk_records: list[dict] = []

    for chunk in chunk_result.chunks:
        chunk_id = ChunkMetadata.generate_chunk_id(doc_id, chunk.chunk_index)

        chunk_meta = ChunkMetadata(
            doc_id=doc_id,
            chunk_id=chunk_id,
            chunk_index=chunk.chunk_index,
            total_chunks=total_chunks,
            section_heading=chunk.section_heading,
            page_number=chunk.page_number,
            start_char=chunk.start_char,
            title=title,
            regulator=regulator.value,
            doc_type=doc_type.value,
            source_url=source_url,
            effective_date=effective_date,
            in_force=in_force,
            language_authority=language_authority.value,
            checksum=parsed.checksum,
        )

        chunk_records.append({
            "text": chunk.text,
            "token_count": chunk.token_count,
            "is_table": chunk.is_table,
            "metadata": chunk_meta.to_chroma_metadata(),
        })

    # ------------------------------------------------------------------
    # Step 5: Persist to JSON
    # ------------------------------------------------------------------
    output_filename = f"{doc_id[:16]}_{_safe_filename(title)}.json"
    output_path = processed_dir / output_filename

    output_data = {
        "doc_id": doc_id,
        "title": title,
        "regulator": regulator.value,
        "doc_type": doc_type.value,
        "source_url": source_url,
        "checksum": parsed.checksum,
        "file_path": str(file_path),
        "file_type": parsed.file_type,
        "page_count": parsed.page_count,
        "total_chunks": total_chunks,
        "total_tokens": chunk_result.total_tokens,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "parse_warnings": parsed.parse_warnings,
        "chunk_warnings": chunk_result.warnings,
        "chunks": chunk_records,
    }

    try:
        output_path.write_text(
            json.dumps(output_data, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info(f"Saved {total_chunks} chunks → {output_path}")
    except Exception as e:
        error_msg = f"Failed to write output file: {e}"
        logger.error(error_msg)
        result = IngestResult(
            success=False,
            doc_id=doc_id,
            file_path=str(file_path),
            title=title,
            regulator=regulator.value,
            doc_type=doc_type.value,
            chunk_count=total_chunks,
            total_tokens=chunk_result.total_tokens,
            page_count=parsed.page_count,
            parse_warnings=parsed.parse_warnings,
            chunk_warnings=chunk_result.warnings,
            error=error_msg,
        )
        _write_log(result, logs_dir)
        return result

    # ------------------------------------------------------------------
    # Step 6: Audit log
    # ------------------------------------------------------------------
    result = IngestResult(
        success=True,
        doc_id=doc_id,
        file_path=str(file_path),
        title=title,
        regulator=regulator.value,
        doc_type=doc_type.value,
        chunk_count=total_chunks,
        total_tokens=chunk_result.total_tokens,
        page_count=parsed.page_count,
        parse_warnings=parsed.parse_warnings,
        chunk_warnings=chunk_result.warnings,
        output_path=str(output_path),
    )
    _write_log(result, logs_dir)

    return result


# ---------------------------------------------------------------------------
# Knowledge base inspection helpers
# ---------------------------------------------------------------------------

def list_ingested_documents(processed_dir: Optional[Path] = None) -> list[dict]:
    """
    Return summary metadata for all ingested documents.

    Returns:
        List of dicts with doc_id, title, regulator, chunk_count, ingested_at.
    """
    processed_dir = processed_dir or _PROCESSED_DIR
    if not processed_dir.exists():
        return []

    summaries: list[dict] = []
    for json_file in sorted(processed_dir.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            summaries.append({
                "doc_id": data.get("doc_id", "unknown")[:16] + "…",
                "title": data.get("title", "unknown"),
                "regulator": data.get("regulator", "unknown"),
                "doc_type": data.get("doc_type", "unknown"),
                "total_chunks": data.get("total_chunks", 0),
                "total_tokens": data.get("total_tokens", 0),
                "page_count": data.get("page_count", 0),
                "ingested_at": data.get("ingested_at", "unknown"),
                "file": json_file.name,
            })
        except Exception as e:
            summaries.append({"file": json_file.name, "error": str(e)})

    return summaries


def get_system_health(
    processed_dir: Optional[Path] = None,
    logs_dir: Optional[Path] = None,
) -> dict:
    """
    Return a system health summary for the CLI.

    Returns:
        Dict with document count, total chunks, total tokens, last ingestion.
    """
    processed_dir = processed_dir or _PROCESSED_DIR
    logs_dir = logs_dir or _LOGS_DIR

    docs = list_ingested_documents(processed_dir)
    total_chunks = sum(d.get("total_chunks", 0) for d in docs if "error" not in d)
    total_tokens = sum(d.get("total_tokens", 0) for d in docs if "error" not in d)
    last_ingested = max(
        (d.get("ingested_at", "") for d in docs if "error" not in d),
        default="never",
    )

    return {
        "document_count": len(docs),
        "total_chunks": total_chunks,
        "total_tokens": total_tokens,
        "last_ingested_at": last_ingested,
        "processed_dir": str(processed_dir),
        "logs_dir": str(logs_dir),
        "processed_dir_exists": processed_dir.exists(),
        "logs_dir_exists": logs_dir.exists(),
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _safe_filename(title: str, max_len: int = 40) -> str:
    """Convert a document title to a safe filename component."""
    safe = re.sub(r"[^\w\-]", "_", title)
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe[:max_len].lower()


def _write_log(result: IngestResult, logs_dir: Path) -> None:
    """Write an ingestion audit log entry."""
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_file = logs_dir / f"ingest_{ts}_{result.doc_id[:8] or 'error'}.json"
        log_file.write_text(
            json.dumps(result.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Failed to write audit log: {e}")


