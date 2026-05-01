"""
tests/test_metadata.py — Tests for DocumentMetadata and ChunkMetadata schemas.
"""

import hashlib
from datetime import date

import pytest
from pydantic import ValidationError

from src.ingestion.metadata import (
    ChunkMetadata,
    DocumentMetadata,
    DocType,
    LanguageAuthority,
    Regulator,
)


def make_metadata(sample_checksum, sample_source_url, **overrides):
    doc_id = DocumentMetadata.generate_doc_id(sample_source_url, sample_checksum)
    defaults = dict(
        doc_id=doc_id,
        title="Test Regulation",
        regulator=Regulator.CBUAE,
        doc_type=DocType.FEDERAL_LAW,
        source_url=sample_source_url,
        checksum=sample_checksum,
        effective_date=date(2025, 1, 1),
        in_force=True,
    )
    defaults.update(overrides)
    return DocumentMetadata(**defaults)


class TestDocumentMetadata:
    """Tests for DocumentMetadata Pydantic model — 7 tests."""

    def test_valid_metadata_creates_successfully(self, sample_checksum, sample_source_url):
        meta = make_metadata(sample_checksum, sample_source_url)
        assert meta.regulator == Regulator.CBUAE
        assert meta.doc_type == DocType.FEDERAL_LAW
        assert meta.in_force is True

    def test_doc_id_is_deterministic(self, sample_checksum, sample_source_url):
        id1 = DocumentMetadata.generate_doc_id(sample_source_url, sample_checksum)
        id2 = DocumentMetadata.generate_doc_id(sample_source_url, sample_checksum)
        assert id1 == id2
        assert len(id1) == 64

    def test_doc_id_changes_when_url_changes(self, sample_checksum):
        id1 = DocumentMetadata.generate_doc_id("https://url1.com/doc", sample_checksum)
        id2 = DocumentMetadata.generate_doc_id("https://url2.com/doc", sample_checksum)
        assert id1 != id2

    def test_invalid_source_url_raises(self, sample_checksum):
        with pytest.raises(ValidationError, match="source_url"):
            doc_id = DocumentMetadata.generate_doc_id("not_a_url", sample_checksum)
            DocumentMetadata(
                doc_id=doc_id,
                title="Test",
                regulator=Regulator.VARA,
                doc_type=DocType.RULEBOOK,
                source_url="not_a_url",
                checksum=sample_checksum,
            )

    def test_invalid_checksum_raises(self, sample_source_url):
        with pytest.raises(ValidationError, match="checksum"):
            DocumentMetadata(
                doc_id="a" * 64,
                title="Test",
                regulator=Regulator.CBUAE,
                doc_type=DocType.CIRCULAR,
                source_url=sample_source_url,
                checksum="not_a_checksum",
            )

    def test_self_supersession_raises(self, sample_checksum, sample_source_url):
        doc_id = DocumentMetadata.generate_doc_id(sample_source_url, sample_checksum)
        with pytest.raises(ValidationError, match="supersede itself"):
            DocumentMetadata(
                doc_id=doc_id,
                title="Test",
                regulator=Regulator.DFSA,
                doc_type=DocType.REGULATION,
                source_url=sample_source_url,
                checksum=sample_checksum,
                supersedes=doc_id,   # self-reference
            )

    def test_all_regulators_are_valid(self, sample_checksum, sample_source_url):
        for reg in Regulator:
            meta = make_metadata(sample_checksum, sample_source_url, regulator=reg)
            assert meta.regulator == reg


class TestChunkMetadata:
    """Tests for ChunkMetadata — 4 tests."""

    def make_chunk_meta(self, sample_doc_metadata, index=0, total=5):
        chunk_id = ChunkMetadata.generate_chunk_id(sample_doc_metadata.doc_id, index)
        return ChunkMetadata(
            doc_id=sample_doc_metadata.doc_id,
            chunk_id=chunk_id,
            chunk_index=index,
            total_chunks=total,
            title=sample_doc_metadata.title,
            regulator=sample_doc_metadata.regulator.value,
            doc_type=sample_doc_metadata.doc_type.value,
            source_url=sample_doc_metadata.source_url,
            checksum=sample_doc_metadata.checksum,
            section_heading="Article 1",
            page_number=1,
        )

    def test_chunk_id_is_deterministic(self, sample_doc_metadata):
        id1 = ChunkMetadata.generate_chunk_id(sample_doc_metadata.doc_id, 3)
        id2 = ChunkMetadata.generate_chunk_id(sample_doc_metadata.doc_id, 3)
        assert id1 == id2 and len(id1) == 64

    def test_chunk_id_differs_by_index(self, sample_doc_metadata):
        id0 = ChunkMetadata.generate_chunk_id(sample_doc_metadata.doc_id, 0)
        id1 = ChunkMetadata.generate_chunk_id(sample_doc_metadata.doc_id, 1)
        assert id0 != id1

    def test_to_chroma_metadata_all_values_are_primitive_types(self, sample_doc_metadata):
        chunk_meta = self.make_chunk_meta(sample_doc_metadata)
        chroma = chunk_meta.to_chroma_metadata()
        for k, v in chroma.items():
            assert isinstance(v, (str, int, float, bool)), (
                f"ChromaDB metadata value for '{k}' is {type(v).__name__}, must be primitive"
            )

    def test_to_chroma_metadata_has_all_required_keys(self, sample_doc_metadata):
        chunk_meta = self.make_chunk_meta(sample_doc_metadata)
        chroma = chunk_meta.to_chroma_metadata()
        required_keys = {
            "doc_id", "chunk_id", "chunk_index", "total_chunks",
            "title", "regulator", "doc_type", "source_url",
            "in_force", "language_authority", "checksum",
            "section_heading", "page_number",
        }
        assert required_keys.issubset(chroma.keys())
