"""
tests/test_parser.py — Tests for document parsing (text and PDF paths).
"""

from pathlib import Path

import pytest

from src.ingestion.parser import (
    ParsedDocument,
    _compute_checksum,
    _detect_structure,
    parse_document,
    parse_text,
    SUPPORTED_EXTENSIONS,
)


class TestTextParser:
    """Tests for parse_text() — 7 tests."""

    def test_parse_cbuae_text_file_returns_parsed_document(self, sample_cbuae_text_file):
        result = parse_text(sample_cbuae_text_file)
        assert isinstance(result, ParsedDocument)
        assert result.file_type == "text"
        assert len(result.raw_text) > 100
        assert result.char_count > 0

    def test_parse_text_computes_correct_checksum(self, sample_cbuae_text_file):
        result = parse_text(sample_cbuae_text_file)
        raw_bytes = sample_cbuae_text_file.read_bytes()
        expected = _compute_checksum(raw_bytes)
        assert result.checksum == expected

    def test_parse_text_detects_article_headings(self, sample_cbuae_text_file):
        result = parse_text(sample_cbuae_text_file)
        headings = [n.heading for n in result.structure]
        # Should detect "Article 2", "Article 3", "Article 4"
        article_headings = [h for h in headings if "Article" in h]
        assert len(article_headings) >= 2

    def test_parse_markdown_detects_headings(self, sample_markdown_file):
        result = parse_text(sample_markdown_file)
        assert result.file_type == "markdown"
        headings = [n.heading for n in result.structure]
        assert any("Guidance" in h or "Background" in h or "Key" in h for h in headings)

    def test_parse_text_raises_for_missing_file(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            parse_text(tmp_dir / "nonexistent.txt")

    def test_parse_text_raises_for_empty_file(self, empty_file):
        with pytest.raises(ValueError, match="empty"):
            parse_text(empty_file)

    def test_parse_document_dispatcher_selects_text(self, sample_vara_text_file):
        result = parse_document(sample_vara_text_file)
        assert result.file_type == "text"
        assert "VARA" in result.raw_text or "Virtual Asset" in result.raw_text

    def test_parse_document_raises_for_unsupported_extension(self, unsupported_file):
        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_document(unsupported_file)

    def test_structure_nodes_sorted_by_char_offset(self, sample_cbuae_text_file):
        result = parse_text(sample_cbuae_text_file)
        offsets = [n.char_offset for n in result.structure]
        assert offsets == sorted(offsets)

    def test_checksum_is_64_char_hex(self, sample_cbuae_text_file):
        result = parse_text(sample_cbuae_text_file)
        assert len(result.checksum) == 64
        assert all(c in "0123456789abcdef" for c in result.checksum)


class TestChecksumFunction:
    """Tests for the checksum utility — 2 tests."""

    def test_same_content_produces_same_checksum(self):
        c1 = _compute_checksum(b"hello")
        c2 = _compute_checksum(b"hello")
        assert c1 == c2

    def test_different_content_produces_different_checksum(self):
        c1 = _compute_checksum(b"hello")
        c2 = _compute_checksum(b"world")
        assert c1 != c2
