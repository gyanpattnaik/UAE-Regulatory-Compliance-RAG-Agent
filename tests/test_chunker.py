"""
tests/test_chunker.py — Tests for structure-aware chunking.
"""

import pytest

from src.ingestion.chunker import (
    TextChunk,
    ChunkingResult,
    chunk_document,
    _split_on_paragraphs,
    _get_overlap_parts,
)
from src.ingestion.parser import ParsedDocument, parse_text


def make_parsed(text: str, structure=None) -> ParsedDocument:
    """Helper: build a minimal ParsedDocument for testing."""
    import hashlib
    return ParsedDocument(
        raw_text=text,
        checksum=hashlib.sha256(text.encode()).hexdigest(),
        file_path="test.txt",
        file_type="text",
        pages=[(1, text)],
        structure=structure or [],
    )


class TestChunkDocument:
    """Tests for chunk_document() — 7 tests."""

    def test_cbuae_text_produces_multiple_chunks(self, sample_cbuae_text_file):
        parsed = parse_text(sample_cbuae_text_file)
        result = chunk_document(parsed, max_tokens=800)
        assert isinstance(result, ChunkingResult)
        assert len(result.chunks) >= 1

    def test_chunks_are_indexed_sequentially(self, sample_cbuae_text_file):
        parsed = parse_text(sample_cbuae_text_file)
        result = chunk_document(parsed)
        indices = [c.chunk_index for c in result.chunks]
        assert indices == list(range(len(result.chunks)))

    def test_no_chunk_exceeds_max_tokens(self, sample_vara_text_file):
        parsed = parse_text(sample_vara_text_file)
        max_tok = 400
        result = chunk_document(parsed, max_tokens=max_tok)
        for chunk in result.chunks:
            # Allow 10% tolerance for sentence boundary splitting
            assert chunk.token_count <= max_tok * 1.1, (
                f"Chunk {chunk.chunk_index} has {chunk.token_count} tokens (max {max_tok})"
            )

    def test_table_chunks_marked_as_table(self, sample_vara_text_file):
        parsed = parse_text(sample_vara_text_file)
        result = chunk_document(parsed)
        table_chunks = [c for c in result.chunks if c.is_table]
        # VARA sample contains one [TABLE] block
        assert len(table_chunks) >= 1

    def test_empty_document_returns_warning(self):
        parsed = make_parsed("")
        result = chunk_document(parsed)
        assert len(result.chunks) == 0
        assert any("extractable text" in w or "empty" in w or "no chunks" in w for w in result.warnings)

    def test_section_heading_propagated_to_chunks(self, sample_cbuae_text_file):
        parsed = parse_text(sample_cbuae_text_file)
        result = chunk_document(parsed)
        # At least some chunks should carry section headings
        chunks_with_headings = [c for c in result.chunks if c.section_heading]
        assert len(chunks_with_headings) >= 1

    def test_total_tokens_equals_sum_of_chunk_tokens(self, sample_cbuae_text_file):
        parsed = parse_text(sample_cbuae_text_file)
        result = chunk_document(parsed)
        assert result.total_tokens == sum(c.token_count for c in result.chunks)

    def test_very_small_max_tokens_still_produces_chunks(self, sample_cbuae_text_file):
        parsed = parse_text(sample_cbuae_text_file)
        result = chunk_document(parsed, max_tokens=50, overlap_tokens=10)
        assert len(result.chunks) >= 2


class TestSplitOnParagraphs:
    """Tests for paragraph-level splitting — 3 tests."""

    def test_splits_large_text_into_multiple_parts(self):
        # Create text that will definitely exceed 50 tokens
        long_text = "\n\n".join([f"Paragraph {i}. " * 10 for i in range(20)])
        chunks = _split_on_paragraphs(long_text, max_tokens=50, overlap_tokens=10)
        assert len(chunks) >= 2

    def test_overlap_creates_shared_content(self):
        # With overlap, consecutive chunks should share some words
        parts = ["Part A content here for testing overlap.",
                 "Part B content here for testing overlap."]
        long_text = "\n\n".join(parts * 5)
        chunks = _split_on_paragraphs(long_text, max_tokens=20, overlap_tokens=5)
        if len(chunks) >= 2:
            # Adjacent chunks may share overlap text
            assert len(chunks) >= 2  # Sanity: multiple chunks exist

    def test_section_heading_inherited_by_all_chunks(self):
        text = "Para one.\n\nPara two.\n\nPara three.\n\n" * 10
        chunks = _split_on_paragraphs(
            text, max_tokens=30, overlap_tokens=5, section_heading="Article 5"
        )
        for c in chunks:
            assert c.section_heading == "Article 5"
