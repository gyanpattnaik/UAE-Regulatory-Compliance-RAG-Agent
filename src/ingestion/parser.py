"""
parser.py — Document parsing for PDF and text/Markdown regulatory documents.

Parsing strategy:
- PDF: pdfplumber primary (preserves layout/tables), pypdf fallback.
- Text/Markdown: direct read with heading detection.

Returns a ParsedDocument with:
- raw_text: full concatenated text
- pages: list of (page_num, text) for PDFs
- structure: detected headings with char offsets
- checksum: SHA-256 of raw bytes (for change detection)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Lazy imports to avoid hard failures if optional deps missing
try:
    import pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False

try:
    from pypdf import PdfReader
    _PYPDF_AVAILABLE = True
except ImportError:
    _PYPDF_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StructureNode:
    """A detected heading/section boundary within a document."""
    heading: str
    char_offset: int          # Position in raw_text where heading appears
    page_number: Optional[int] = None
    level: int = 1            # 1=Article/Chapter, 2=Section, 3=Sub-section


@dataclass
class ParsedDocument:
    """Output of the parser — everything downstream needs to chunk + embed."""
    raw_text: str
    checksum: str             # SHA-256 of original file bytes
    file_path: str
    file_type: str            # "pdf" | "text" | "markdown"
    pages: list[tuple[int, str]] = field(default_factory=list)  # (page_num, text)
    structure: list[StructureNode] = field(default_factory=list)
    parse_warnings: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages) if self.pages else 1

    @property
    def char_count(self) -> int:
        return len(self.raw_text)


# ---------------------------------------------------------------------------
# Heading detection patterns (UAE regulatory document conventions)
# ---------------------------------------------------------------------------

# Matches: "Article 12", "ARTICLE 3", "Chapter IV", "Section 2.1", "Clause 5"
_HEADING_PATTERNS = [
    # Article-level (highest hierarchy)
    (re.compile(r"^(Article|ARTICLE)\s+\d+[\w\.\-]*", re.MULTILINE), 1),
    # Chapter-level
    (re.compile(r"^(Chapter|CHAPTER|Part|PART)\s+[\dIVXivx]+", re.MULTILINE), 1),
    # Section-level
    (re.compile(r"^(Section|SECTION)\s+[\d\.]+", re.MULTILINE), 2),
    # Numbered sub-clauses like "1.", "2.1", "3.1.2" at line start
    (re.compile(r"^\d+\.\d*\s{2,}", re.MULTILINE), 2),
    # All-caps standalone lines (common for major headings in regulatory PDFs)
    (re.compile(r"^[A-Z][A-Z\s]{10,}$", re.MULTILINE), 2),
]


def _detect_structure(text: str, page_map: dict[int, int] | None = None) -> list[StructureNode]:
    """
    Detect section/article boundaries in extracted text.

    Args:
        text: Full document text.
        page_map: Optional mapping of char_offset → page_number.

    Returns:
        Sorted list of StructureNodes.
    """
    nodes: list[StructureNode] = []
    seen_offsets: set[int] = set()

    for pattern, level in _HEADING_PATTERNS:
        for match in pattern.finditer(text):
            offset = match.start()
            if offset in seen_offsets:
                continue
            seen_offsets.add(offset)

            heading_text = match.group(0).strip()
            page_num = None
            if page_map:
                # Find the page this offset falls on
                for char_start, pnum in sorted(page_map.items()):
                    if char_start <= offset:
                        page_num = pnum

            nodes.append(StructureNode(
                heading=heading_text,
                char_offset=offset,
                page_number=page_num,
                level=level,
            ))

    return sorted(nodes, key=lambda n: n.char_offset)


def _compute_checksum(raw_bytes: bytes) -> str:
    """Return SHA-256 hex digest of raw file bytes."""
    return hashlib.sha256(raw_bytes).hexdigest()


# ---------------------------------------------------------------------------
# PDF parsing
# ---------------------------------------------------------------------------

def _parse_pdf_pdfplumber(path: Path) -> tuple[list[tuple[int, str]], list[str]]:
    """
    Parse PDF using pdfplumber (primary strategy).
    Returns (pages, warnings).
    """
    pages: list[tuple[int, str]] = []
    warnings: list[str] = []

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                # Also extract tables as text blocks
                tables = page.extract_tables()
                for table in tables:
                    rows = ["\t".join(str(cell or "") for cell in row) for row in table if row]
                    text += "\n\n[TABLE]\n" + "\n".join(rows) + "\n[/TABLE]\n"
                pages.append((i, text))
            except Exception as e:
                warnings.append(f"Page {i}: pdfplumber extraction error: {e}")
                pages.append((i, ""))

    return pages, warnings


def _parse_pdf_pypdf(path: Path) -> tuple[list[tuple[int, str]], list[str]]:
    """
    Parse PDF using pypdf (fallback strategy).
    Returns (pages, warnings).
    """
    pages: list[tuple[int, str]] = []
    warnings: list[str] = []

    reader = PdfReader(str(path))
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
            pages.append((i, text))
        except Exception as e:
            warnings.append(f"Page {i}: pypdf extraction error: {e}")
            pages.append((i, ""))

    return pages, warnings


def parse_pdf(path: Path) -> ParsedDocument:
    """
    Parse a PDF regulatory document.

    Strategy:
    1. Try pdfplumber (handles layout + tables)
    2. Fall back to pypdf if pdfplumber fails or unavailable
    3. If both fail, raise RuntimeError with clear message

    Args:
        path: Path to the PDF file.

    Returns:
        ParsedDocument with full text, structure, and checksum.

    Raises:
        FileNotFoundError: If file doesn't exist.
        RuntimeError: If no PDF parser is available or parsing fails.
        ValueError: If file is empty.
    """
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"PDF file is empty: {path}")

    raw_bytes = path.read_bytes()
    checksum = _compute_checksum(raw_bytes)

    pages: list[tuple[int, str]] = []
    warnings: list[str] = []

    # Strategy 1: pdfplumber
    if _PDFPLUMBER_AVAILABLE:
        try:
            pages, warnings = _parse_pdf_pdfplumber(path)
        except Exception as e:
            warnings.append(f"pdfplumber failed: {e}. Trying pypdf fallback.")
            pages = []

    # Strategy 2: pypdf fallback
    if not pages and _PYPDF_AVAILABLE:
        try:
            fallback_pages, fallback_warnings = _parse_pdf_pypdf(path)
            pages = fallback_pages
            warnings.extend(fallback_warnings)
            if pages:
                warnings.append("Used pypdf fallback (pdfplumber unavailable or failed).")
        except Exception as e:
            warnings.append(f"pypdf also failed: {e}")

    if not pages:
        raise RuntimeError(
            f"Failed to parse PDF: {path}. "
            "Ensure pdfplumber or pypdf is installed: pip install pdfplumber pypdf"
        )

    # Combine all page text
    raw_text = "\n\n".join(text for _, text in pages if text.strip())

    if not raw_text.strip():
        warnings.append(
            "PDF parsed but no text extracted — document may be image-based (scanned). "
            "OCR is not supported in MVP."
        )

    # Build page_map: char_offset → page_number for structure detection
    page_map: dict[int, int] = {}
    offset = 0
    for page_num, text in pages:
        page_map[offset] = page_num
        offset += len(text) + 2  # +2 for the "\n\n" join

    structure = _detect_structure(raw_text, page_map=page_map)

    return ParsedDocument(
        raw_text=raw_text,
        checksum=checksum,
        file_path=str(path),
        file_type="pdf",
        pages=pages,
        structure=structure,
        parse_warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Text / Markdown parsing
# ---------------------------------------------------------------------------

def parse_text(path: Path) -> ParsedDocument:
    """
    Parse a plain text or Markdown regulatory document.

    Detects headings using the same patterns as PDF, plus Markdown
    heading syntax (# / ## / ###).

    Args:
        path: Path to .txt or .md file.

    Returns:
        ParsedDocument.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If file is empty.
        UnicodeDecodeError: If file encoding is not UTF-8 or latin-1.
    """
    if not path.exists():
        raise FileNotFoundError(f"Text file not found: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"Text file is empty: {path}")

    raw_bytes = path.read_bytes()
    checksum = _compute_checksum(raw_bytes)

    # Try UTF-8 first, fall back to latin-1
    warnings: list[str] = []
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raw_text = raw_bytes.decode("latin-1")
        warnings.append("File decoded as latin-1 (not UTF-8). Check source encoding.")

    if not raw_text.strip():
        raise ValueError(f"Text file is empty after decoding: {path}")

    suffix = path.suffix.lower()
    file_type = "markdown" if suffix in (".md", ".markdown") else "text"

    # For Markdown: detect ATX headings (#, ##, ###) in addition to regulatory patterns
    structure: list[StructureNode] = []
    if file_type == "markdown":
        md_heading = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
        level_map = {"#": 1, "##": 2, "###": 3}
        for match in md_heading.finditer(raw_text):
            hashes = match.group(1)
            text = match.group(2).strip()
            structure.append(StructureNode(
                heading=text,
                char_offset=match.start(),
                level=level_map.get(hashes, 2),
            ))

    # Also apply regulatory heading patterns
    regulatory_structure = _detect_structure(raw_text)
    # Merge and deduplicate by char_offset
    existing_offsets = {n.char_offset for n in structure}
    for node in regulatory_structure:
        if node.char_offset not in existing_offsets:
            structure.append(node)
            existing_offsets.add(node.char_offset)

    structure.sort(key=lambda n: n.char_offset)

    return ParsedDocument(
        raw_text=raw_text,
        checksum=checksum,
        file_path=str(path),
        file_type=file_type,
        pages=[(1, raw_text)],    # Text files treated as single-page
        structure=structure,
        parse_warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown"}


def parse_document(path: Path) -> ParsedDocument:
    """
    Parse a regulatory document, auto-detecting format from file extension.

    Args:
        path: Path to the document file.

    Returns:
        ParsedDocument.

    Raises:
        ValueError: If file extension is not supported.
        FileNotFoundError: If file doesn't exist.
    """
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {suffix!r}. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if suffix == ".pdf":
        return parse_pdf(path)
    else:
        return parse_text(path)
