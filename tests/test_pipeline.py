"""
tests/test_pipeline.py — Integration tests for the full ingestion pipeline.
"""

import json
from datetime import date
from pathlib import Path

import pytest

from src.ingestion.metadata import DocType, LanguageAuthority, Regulator
from src.ingestion.pipeline import (
    IngestResult,
    get_system_health,
    ingest_document,
    list_ingested_documents,
)


class TestIngestDocument:
    """Integration tests for ingest_document() — 6 tests."""

    def _ingest_cbuae(self, file_path, processed_dir, logs_dir):
        return ingest_document(
            file_path=file_path,
            title="CBUAE Test Regulation",
            regulator=Regulator.CBUAE,
            doc_type=DocType.REGULATION,
            source_url="https://uaelegislation.gov.ae/en/legislations/3284",
            effective_date=date(2025, 1, 1),
            language_authority=LanguageAuthority.EN_TRANSLATION,
            in_force=True,
            processed_dir=processed_dir,
            logs_dir=logs_dir,
        )

    def test_successful_ingestion_returns_success_result(
        self, sample_cbuae_text_file, tmp_dir
    ):
        result = self._ingest_cbuae(
            sample_cbuae_text_file, tmp_dir / "processed", tmp_dir / "logs"
        )
        assert result.success is True
        assert result.chunk_count > 0
        assert result.total_tokens > 0
        assert result.error is None

    def test_ingestion_writes_json_output_file(
        self, sample_cbuae_text_file, tmp_dir
    ):
        processed = tmp_dir / "processed"
        result = self._ingest_cbuae(
            sample_cbuae_text_file, processed, tmp_dir / "logs"
        )
        assert result.output_path is not None
        output_file = Path(result.output_path)
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert "chunks" in data
        assert len(data["chunks"]) == result.chunk_count

    def test_ingestion_writes_audit_log(
        self, sample_cbuae_text_file, tmp_dir
    ):
        logs = tmp_dir / "logs"
        self._ingest_cbuae(
            sample_cbuae_text_file, tmp_dir / "processed", logs
        )
        log_files = list(logs.glob("ingest_*.json"))
        assert len(log_files) >= 1

    def test_output_chunks_have_required_metadata_keys(
        self, sample_cbuae_text_file, tmp_dir
    ):
        processed = tmp_dir / "processed"
        result = self._ingest_cbuae(
            sample_cbuae_text_file, processed, tmp_dir / "logs"
        )
        data = json.loads(Path(result.output_path).read_text())
        first_chunk = data["chunks"][0]
        required = {"text", "token_count", "metadata"}
        assert required.issubset(first_chunk.keys())
        meta = first_chunk["metadata"]
        meta_required = {
            "doc_id", "chunk_id", "chunk_index", "total_chunks",
            "title", "regulator", "source_url", "checksum"
        }
        assert meta_required.issubset(meta.keys())

    def test_ingestion_fails_gracefully_for_missing_file(self, tmp_dir):
        result = ingest_document(
            file_path=tmp_dir / "nonexistent.txt",
            title="Test",
            regulator=Regulator.VARA,
            doc_type=DocType.RULEBOOK,
            source_url="https://rulebooks.vara.ae/",
            processed_dir=tmp_dir / "processed",
            logs_dir=tmp_dir / "logs",
        )
        assert result.success is False
        assert result.error is not None
        assert "not found" in result.error.lower() or "parse" in result.error.lower()

    def test_doc_id_is_deterministic_across_re_ingestion(
        self, sample_cbuae_text_file, tmp_dir
    ):
        r1 = self._ingest_cbuae(
            sample_cbuae_text_file, tmp_dir / "p1", tmp_dir / "l1"
        )
        r2 = self._ingest_cbuae(
            sample_cbuae_text_file, tmp_dir / "p2", tmp_dir / "l2"
        )
        assert r1.doc_id == r2.doc_id


class TestListAndHealth:
    """Tests for list_ingested_documents() and get_system_health() — 3 tests."""

    def test_list_returns_empty_for_fresh_directory(self, tmp_dir):
        docs = list_ingested_documents(tmp_dir / "processed")
        assert docs == []

    def test_list_returns_one_entry_after_ingestion(
        self, sample_cbuae_text_file, tmp_dir
    ):
        processed = tmp_dir / "processed"
        ingest_document(
            file_path=sample_cbuae_text_file,
            title="CBUAE Reg",
            regulator=Regulator.CBUAE,
            doc_type=DocType.REGULATION,
            source_url="https://uaelegislation.gov.ae/en/legislations/3284",
            processed_dir=processed,
            logs_dir=tmp_dir / "logs",
        )
        docs = list_ingested_documents(processed)
        assert len(docs) == 1
        assert docs[0]["regulator"] == "CBUAE"

    def test_health_returns_correct_document_count(
        self, sample_cbuae_text_file, tmp_dir
    ):
        processed = tmp_dir / "processed"
        ingest_document(
            file_path=sample_cbuae_text_file,
            title="CBUAE Reg",
            regulator=Regulator.CBUAE,
            doc_type=DocType.REGULATION,
            source_url="https://uaelegislation.gov.ae/en/legislations/3284",
            processed_dir=processed,
            logs_dir=tmp_dir / "logs",
        )
        health = get_system_health(processed, tmp_dir / "logs")
        assert health["document_count"] == 1
        assert health["total_chunks"] >= 1
