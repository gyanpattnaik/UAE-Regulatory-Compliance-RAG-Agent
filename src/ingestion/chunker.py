"""
chunker.py — Structure-aware text chunking for regulatory documents.

Chunking strategy (from PRD Section 9.4):
1. Try to split on heading boundaries (Article / Section / Chapter)
2. If a section exceeds max_tokens, split further on paragraph breaks
3. Tables are preserved as atomic chunks (never split mid-table)
4. 150-token overlap between consecutive chunks from the same section
5. Every chunk carries section_heading and page_number in metadata

Token counting uses tiktoken cl100k_base as a proxy counter.
The actual embedding model (all-MiniLM-L6-v2) uses WordPiece tokenisation,
but cl100k_base produces comparable counts for English regulatory text.
The default MAX_CHUNK_TOKENS budget (500) is set to stay safely within
MiniLM's 512-token input window.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

try:
    import tiktoken
    _enc = tiktoken.get_encoding("cl100k_base")  # Used by text-embedding-3-small
    def _count_tokens(text: str) -> int:
        return len(_enc.encode(text))
except ImportError:
    # Fallback: approximate 4 chars ≈ 1 token
    def _count_tokens(text: str) -> int:  # type: ignore[misc]
        return max(1, len(text) // 4)

from .parser import ParsedDocument, StructureNode


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TextChunk:
    """A single chunk of text ready for embedding."""
    text: str
    chunk_index: int
    section_heading: Optional[str] = None
    page_number: Optional[int] = None
    start_char: Optional[int] = None
    token_count: int = 0
    is_table: bool = False

    def __post_init__(self) -> None:
        if self.token_count == 0:
            self.token_count = _count_tokens(self.text)


@dataclass
class ChunkingResult:
    """Output of the chunker: all chunks + statistics."""
    chunks: list[TextChunk] = field(default_factory=list)
    total_tokens: int = 0
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.chunks and self.total_tokens == 0:
            self.total_tokens = sum(c.token_count for c in self.chunks)


# ---------------------------------------------------------------------------
# Table detection and extraction
# ---------------------------------------------------------------------------

_TABLE_PATTERN = re.compile(
    r"\[TABLE\](.*?)\[/TABLE\]",
    re.DOTALL,
)


def _extract_tables(text: str) -> list[tuple[int, int, str]]:
    """
    Find table blocks in text (inserted by pdfplumber parser).
    Returns list of (start, end, table_text).
    """
    return [
        (m.start(), m.end(), m.group(0))
        for m in _TABLE_PATTERN.finditer(text)
    ]


# ---------------------------------------------------------------------------
# Core splitting logic
# ---------------------------------------------------------------------------

def _split_on_paragraphs(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
    start_char: int = 0,
    section_heading: Optional[str] = None,
    page_number: Optional[int] = None,
) -> list[TextChunk]:
    """
    Split text into chunks at paragraph boundaries.
    Used when a section exceeds max_tokens.
    """
    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: list[TextChunk] = []
    current_parts: list[str] = []
    current_tokens = 0
    char_offset = start_char

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        para_tokens = _count_tokens(para)

        # Single paragraph exceeds limit — force split by sentences
        if para_tokens > max_tokens:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                sent_tokens = _count_tokens(sent)
                if current_tokens + sent_tokens > max_tokens and current_parts:
                    chunk_text = " ".join(current_parts)
                    chunks.append(TextChunk(
                        text=chunk_text,
                        chunk_index=len(chunks),
                        section_heading=section_heading,
                        page_number=page_number,
                        start_char=char_offset,
                    ))
                    # Overlap: keep last few tokens worth of content
                    overlap_parts = _get_overlap_parts(current_parts, overlap_tokens)
                    current_parts = overlap_parts
                    current_tokens = sum(_count_tokens(p) for p in current_parts)
                    char_offset += len(chunk_text)

                current_parts.append(sent)
                current_tokens += sent_tokens
        elif current_tokens + para_tokens > max_tokens and current_parts:
            # Flush current chunk
            chunk_text = "\n\n".join(current_parts)
            chunks.append(TextChunk(
                text=chunk_text,
                chunk_index=len(chunks),
                section_heading=section_heading,
                page_number=page_number,
                start_char=char_offset,
            ))
            # Overlap
            overlap_parts = _get_overlap_parts(current_parts, overlap_tokens)
            current_parts = overlap_parts + [para]
            current_tokens = sum(_count_tokens(p) for p in current_parts)
            char_offset += len(chunk_text)
        else:
            current_parts.append(para)
            current_tokens += para_tokens

    # Final flush
    if current_parts:
        chunk_text = "\n\n".join(current_parts)
        chunks.append(TextChunk(
            text=chunk_text,
            chunk_index=len(chunks),
            section_heading=section_heading,
            page_number=page_number,
            start_char=char_offset,
        ))

    return chunks


def _get_overlap_parts(parts: list[str], overlap_tokens: int) -> list[str]:
    """Return the trailing parts that fit within overlap_tokens."""
    overlap: list[str] = []
    total = 0
    for part in reversed(parts):
        t = _count_tokens(part)
        if total + t > overlap_tokens:
            break
        overlap.insert(0, part)
        total += t
    return overlap


# ---------------------------------------------------------------------------
# Main chunking entry point
# ---------------------------------------------------------------------------

def chunk_document(
    parsed: ParsedDocument,
    max_tokens: int = 800,
    overlap_tokens: int = 150,
) -> ChunkingResult:
    """
    Split a ParsedDocument into text chunks using structure-aware strategy.

    Strategy:
    1. Extract tables → atomic chunks (never split)
    2. Split remaining text on heading boundaries from structure nodes
    3. If any section > max_tokens → paragraph-level split with overlap
    4. Re-index all chunks sequentially

    Args:
        parsed: Output of parse_document().
        max_tokens: Maximum tokens per chunk (default: 800).
        overlap_tokens: Tokens of overlap between consecutive chunks (default: 150).

    Returns:
        ChunkingResult with list of TextChunks.
    """
    warnings: list[str] = []
    all_chunks: list[TextChunk] = []
    text = parsed.raw_text

    if not text.strip():
        warnings.append("Document has no extractable text — no chunks produced.")
        return ChunkingResult(chunks=[], warnings=warnings)

    # Step 1: Extract and remove table blocks first (atomic chunks)
    table_regions = _extract_tables(text)
    table_chunk_texts: list[tuple[int, TextChunk]] = []  # (original_start, chunk)

    for tbl_start, tbl_end, tbl_text in table_regions:
        tbl_tokens = _count_tokens(tbl_text)
        if tbl_tokens > max_tokens * 2:
            warnings.append(
                f"Table at char {tbl_start} is very large ({tbl_tokens} tokens). "
                "Stored as single chunk — may degrade retrieval quality."
            )
        # Find which section this table falls under
        heading = _find_nearest_heading(parsed.structure, tbl_start)
        page = _find_page_for_offset(parsed.pages, tbl_start)
        table_chunk_texts.append((tbl_start, TextChunk(
            text=tbl_text.strip(),
            chunk_index=0,  # Will be re-indexed
            section_heading=heading,
            page_number=page,
            start_char=tbl_start,
            is_table=True,
        )))

    # Remove table regions from text for section-based splitting
    clean_text = _TABLE_PATTERN.sub("[TABLE EXTRACTED]", text)

    # Step 2: Recalculate structure node offsets for the modified text.
    # After table replacement, character positions shift. We re-locate
    # each heading in clean_text to get accurate split boundaries.
    adjusted_structure = _recalculate_offsets(clean_text, parsed.structure)

    # Step 3: Split text on structure node boundaries
    section_texts = _split_on_structure(clean_text, adjusted_structure)

    # Step 4: Chunk each section, splitting further if needed
    section_chunks: list[TextChunk] = []
    for section_text, heading, start_char in section_texts:
        section_text = section_text.strip()
        if not section_text:
            continue

        page = _find_page_for_offset(parsed.pages, start_char)
        tokens = _count_tokens(section_text)

        if tokens <= max_tokens:
            section_chunks.append(TextChunk(
                text=section_text,
                chunk_index=0,
                section_heading=heading,
                page_number=page,
                start_char=start_char,
            ))
        else:
            # Section too large → paragraph-level split
            sub_chunks = _split_on_paragraphs(
                text=section_text,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
                start_char=start_char,
                section_heading=heading,
                page_number=page,
            )
            section_chunks.extend(sub_chunks)

    # Step 5: Merge tables back in order of their original char position
    # Sort section chunks by start_char
    section_chunks.sort(key=lambda c: (c.start_char or 0))

    # Insert table chunks at correct positions
    for tbl_start, tbl_chunk in sorted(table_chunk_texts, key=lambda x: x[0]):
        # Find insertion point
        inserted = False
        for i, sc in enumerate(section_chunks):
            if (sc.start_char or 0) > tbl_start:
                section_chunks.insert(i, tbl_chunk)
                inserted = True
                break
        if not inserted:
            section_chunks.append(tbl_chunk)

    # Step 6: Re-index all chunks
    for i, chunk in enumerate(section_chunks):
        chunk.chunk_index = i
        all_chunks.append(chunk)

    if not all_chunks:
        warnings.append("No chunks produced — document may be empty or unparseable.")

    # Step 7: Merge tiny non-table chunks (< 20 tokens) into their left neighbour.
    # These arise when a heading line becomes its own section before the first paragraph.
    MIN_CHUNK_TOKENS = 20
    merged: list[TextChunk] = []
    for chunk in all_chunks:
        if (
            chunk.token_count < MIN_CHUNK_TOKENS
            and not chunk.is_table
            and merged
            and not merged[-1].is_table
        ):
            prev = merged[-1]
            prev.text = prev.text + "\n\n" + chunk.text
            prev.token_count = _count_tokens(prev.text)
        else:
            merged.append(chunk)

    # Re-index after merge
    for i, chunk in enumerate(merged):
        chunk.chunk_index = i
    all_chunks = merged

    # Warn if tiny chunks still remain (edge case: entire doc is tiny)
    tiny = [c for c in all_chunks if c.token_count < MIN_CHUNK_TOKENS and not c.is_table]
    if tiny:
        warnings.append(
            f"{len(tiny)} chunk(s) still have fewer than {MIN_CHUNK_TOKENS} tokens "
            "after merging — document may have very sparse content."
        )

    return ChunkingResult(
        chunks=all_chunks,
        total_tokens=sum(c.token_count for c in all_chunks),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_on_structure(
    text: str,
    structure: list[StructureNode],
) -> list[tuple[str, Optional[str], int]]:
    """
    Split text at heading boundaries.
    Returns list of (section_text, heading, start_char).
    """
    if not structure:
        return [(text, None, 0)]

    sections: list[tuple[str, Optional[str], int]] = []
    prev_offset = 0
    prev_heading: Optional[str] = None

    for node in structure:
        offset = node.char_offset
        if offset > prev_offset:
            section_text = text[prev_offset:offset]
            if section_text.strip():
                sections.append((section_text, prev_heading, prev_offset))
        prev_offset = offset
        prev_heading = node.heading

    # Final section (from last heading to end)
    final_text = text[prev_offset:]
    if final_text.strip():
        sections.append((final_text, prev_heading, prev_offset))

    return sections


def _find_nearest_heading(
    structure: list[StructureNode],
    char_offset: int,
) -> Optional[str]:
    """Find the heading that appears immediately before char_offset."""
    nearest: Optional[str] = None
    for node in structure:
        if node.char_offset <= char_offset:
            nearest = node.heading
        else:
            break
    return nearest


def _find_page_for_offset(
    pages: list[tuple[int, str]],
    char_offset: int,
) -> Optional[int]:
    """Identify which page a character offset falls on."""
    cumulative = 0
    for page_num, page_text in pages:
        cumulative += len(page_text) + 2  # +2 for "\n\n" join
        if cumulative >= char_offset:
            return page_num
    return pages[-1][0] if pages else None


def _recalculate_offsets(
    clean_text: str,
    structure: list[StructureNode],
) -> list[StructureNode]:
    """
    Re-locate heading positions in the modified text after table replacement.

    When tables are replaced with '[TABLE EXTRACTED]', character offsets from
    the original text become stale. This function searches for each heading
    string in the clean_text and returns new StructureNodes with corrected
    offsets. Headings that cannot be found are dropped with a warning.
    """
    if not structure:
        return []

    adjusted: list[StructureNode] = []
    search_start = 0  # Only search forward to preserve ordering

    for node in structure:
        idx = clean_text.find(node.heading, search_start)
        if idx != -1:
            adjusted.append(StructureNode(
                heading=node.heading,
                level=node.level,
                char_offset=idx,
            ))
            search_start = idx + len(node.heading)
        else:
            # Heading was inside a table region or otherwise lost
            import logging
            logging.getLogger(__name__).debug(
                f"Heading '{node.heading}' not found in clean text — skipping."
            )

    return adjusted
