"""
metadata.py — DocumentMetadata schema and validation.

Every ingested chunk carries this metadata. The schema is the contract
between ingestion (Build Step 1) and retrieval (Build Step 2).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Regulator(str, Enum):
    """UAE regulatory bodies supported by this system."""
    CBUAE = "CBUAE"   # Central Bank of UAE
    VARA = "VARA"     # Virtual Assets Regulatory Authority (Dubai)
    CMA = "CMA"       # Capital Markets Authority (formerly SCA)
    DFSA = "DFSA"     # Dubai Financial Services Authority (DIFC)
    FSRA = "FSRA"     # Financial Services Regulatory Authority (ADGM)


class DocType(str, Enum):
    """Classification of regulatory document type."""
    FEDERAL_LAW = "federal_law"
    REGULATION = "regulation"
    CIRCULAR = "circular"
    GUIDANCE = "guidance"
    RULEBOOK = "rulebook"
    THEMATIC_REVIEW = "thematic_review"
    CONSULTATION = "consultation"
    ENFORCEMENT = "enforcement"


class LanguageAuthority(str, Enum):
    """Indicates the legal authority of the document's language."""
    EN_AUTHORITATIVE = "en_authoritative"   # English is the legally authoritative version
    EN_TRANSLATION = "en_translation"       # English is a translation (Arabic is authoritative)
    AR_AUTHORITATIVE = "ar_authoritative"   # Arabic authoritative (not yet supported in MVP)


class DocumentMetadata(BaseModel):
    """
    Metadata schema for a single regulatory document.

    Follows the PRD Section 10 specification. Every ingested document
    must carry this metadata before chunking begins.
    """

    # Identity
    doc_id: str = Field(description="Deterministic SHA-256 hash of source_url + checksum")
    title: str = Field(description="Official document title")
    regulator: Regulator = Field(description="Issuing regulatory body")
    doc_type: DocType = Field(description="Type of regulatory document")

    # Source provenance
    source_url: str = Field(description="Official public URL of the document")
    retrieved_date: date = Field(
        default_factory=date.today,
        description="Date this document was downloaded/ingested",
    )
    effective_date: Optional[date] = Field(
        default=None,
        description="Date the regulation came into force (if known)",
    )
    checksum: str = Field(description="SHA-256 of raw document bytes for change detection")

    # Legal authority
    language_authority: LanguageAuthority = Field(
        default=LanguageAuthority.EN_TRANSLATION,
        description="Legal authority of document language",
    )
    in_force: bool = Field(
        default=True,
        description="Whether this document is currently in force",
    )

    # Amendment chains
    supersedes: Optional[str] = Field(
        default=None,
        description="doc_id of the document this one supersedes",
    )
    superseded_by: Optional[str] = Field(
        default=None,
        description="doc_id of the document that supersedes this one",
    )

    # Freshness
    last_verified: date = Field(
        default_factory=date.today,
        description="Date the in_force status was last manually verified",
    )

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, v: str) -> str:
        """Ensure URL is a non-empty HTTPS link to a public source."""
        if not v.startswith("http"):
            raise ValueError(f"source_url must be an HTTP(S) URL, got: {v!r}")
        return v

    @field_validator("checksum")
    @classmethod
    def validate_checksum(cls, v: str) -> str:
        """Ensure checksum is a valid 64-character hex SHA-256."""
        if len(v) != 64 or not all(c in "0123456789abcdef" for c in v.lower()):
            raise ValueError(f"checksum must be a 64-character hex SHA-256, got: {v!r}")
        return v.lower()

    @model_validator(mode="after")
    def validate_supersession_not_self(self) -> "DocumentMetadata":
        """A document cannot supersede itself."""
        if self.supersedes and self.supersedes == self.doc_id:
            raise ValueError("A document cannot supersede itself.")
        if self.superseded_by and self.superseded_by == self.doc_id:
            raise ValueError("A document cannot be superseded by itself.")
        return self

    @classmethod
    def generate_doc_id(cls, source_url: str, checksum: str) -> str:
        """Generate a deterministic doc_id from source_url and checksum."""
        raw = f"{source_url}::{checksum}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class ChunkMetadata(BaseModel):
    """
    Metadata for a single text chunk derived from a document.

    Extends DocumentMetadata with chunk-specific fields. This is what
    gets stored alongside each vector in ChromaDB.
    """

    # Parent document identity
    doc_id: str
    chunk_id: str = Field(description="Deterministic hash: doc_id + chunk_index")
    chunk_index: int = Field(ge=0, description="Zero-based index of this chunk")
    total_chunks: int = Field(ge=1)

    # Source location within document
    section_heading: Optional[str] = Field(
        default=None,
        description="Nearest heading above this chunk (Article/Section/Chapter)",
    )
    page_number: Optional[int] = Field(
        default=None,
        description="Page number in source PDF (1-indexed)",
    )
    start_char: Optional[int] = Field(
        default=None,
        description="Character offset of chunk start within full document text",
    )

    # Inherited document metadata (denormalised for retrieval efficiency)
    title: str
    regulator: str
    doc_type: str
    source_url: str
    effective_date: Optional[date] = None
    in_force: bool = True
    language_authority: str = LanguageAuthority.EN_TRANSLATION.value
    retrieved_date: date = Field(default_factory=date.today)
    last_verified: date = Field(default_factory=date.today)
    checksum: str

    @classmethod
    def generate_chunk_id(cls, doc_id: str, chunk_index: int) -> str:
        """Generate a deterministic chunk_id."""
        raw = f"{doc_id}::chunk::{chunk_index}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def to_chroma_metadata(self) -> dict:
        """
        Serialise to a flat dict suitable for ChromaDB metadata storage.
        ChromaDB requires all values to be str, int, float, or bool.
        """
        return {
            "doc_id": self.doc_id,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "title": self.title,
            "regulator": self.regulator,
            "doc_type": self.doc_type,
            "source_url": self.source_url,
            "effective_date": str(self.effective_date) if self.effective_date else "",
            "in_force": self.in_force,
            "language_authority": self.language_authority,
            "retrieved_date": str(self.retrieved_date),
            "last_verified": str(self.last_verified),
            "checksum": self.checksum,
            "section_heading": self.section_heading or "",
            "page_number": self.page_number or 0,
            "start_char": self.start_char or 0,
        }
