"""
tests/conftest.py — Shared fixtures for ingestion pipeline tests.
"""

import hashlib
import tempfile
from datetime import date
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Sample document text fixtures
# ---------------------------------------------------------------------------

SAMPLE_CBUAE_TEXT = """\
# CBUAE Sample Regulation

## Article 1 — Definitions

For the purpose of this Regulation, the following definitions shall apply:

1.1 "Institution" means any licensed financial institution under the supervision of the Central Bank.

1.2 "AML" means Anti-Money Laundering measures as defined under applicable law.

Article 2 — Obligations

Every Institution shall maintain adequate internal controls to detect and prevent money
laundering and terrorist financing. Institutions must submit quarterly reports to the
Central Bank no later than 15 days after the end of each quarter.

Article 3 — Reporting Requirements

All Institutions shall report suspicious transactions to the Financial Intelligence Unit
within 24 hours of detection. Failure to comply shall result in administrative penalties.

Article 4 — Record Keeping

Institutions are required to maintain records of all transactions for a minimum period
of five (5) years from the date of transaction completion.
"""

SAMPLE_VARA_TEXT = """\
# VARA Rulebook — Virtual Asset Service Providers

Section 1 — Scope of Application

This Rulebook applies to all Virtual Asset Service Providers (VASPs) licensed or
seeking a license to operate within the Emirate of Dubai.

Section 2 — Licensing Requirements

2.1 All VASPs must obtain a VARA license prior to commencing operations.

2.2 License applications shall include:
   - Proof of adequate financial resources
   - AML/CFT compliance framework
   - Technology risk management policy

Section 3 — AML Obligations

VASPs shall implement robust AML/CFT measures including:
- Customer Due Diligence (CDD) for all customers
- Enhanced Due Diligence (EDD) for high-risk customers
- Travel Rule compliance for transfers above USD 1,000

[TABLE]
Threshold\tRequirement\tTimeline
USD 1,000\tTravel Rule\tImmediate
USD 10,000\tEnhanced CDD\t48 hours
[/TABLE]
"""

SAMPLE_SMALL_TEXT = "This is a very short document with minimal content."

SAMPLE_MARKDOWN_TEXT = """\
# Guidance Note

## Background

This guidance note provides clarity on regulatory expectations.

### Key Requirements

Firms must comply with all applicable regulations.
"""


# ---------------------------------------------------------------------------
# File fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir():
    """Temporary directory that is cleaned up after each test."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def sample_cbuae_text_file(tmp_dir):
    """A sample CBUAE regulation as a .txt file."""
    f = tmp_dir / "cbuae_sample.txt"
    f.write_text(SAMPLE_CBUAE_TEXT, encoding="utf-8")
    return f


@pytest.fixture
def sample_vara_text_file(tmp_dir):
    """A sample VARA rulebook as a .txt file."""
    f = tmp_dir / "vara_sample.txt"
    f.write_text(SAMPLE_VARA_TEXT, encoding="utf-8")
    return f


@pytest.fixture
def sample_markdown_file(tmp_dir):
    """A sample Markdown guidance note."""
    f = tmp_dir / "guidance.md"
    f.write_text(SAMPLE_MARKDOWN_TEXT, encoding="utf-8")
    return f


@pytest.fixture
def sample_small_text_file(tmp_dir):
    """A tiny text file for edge case testing."""
    f = tmp_dir / "small.txt"
    f.write_text(SAMPLE_SMALL_TEXT, encoding="utf-8")
    return f


@pytest.fixture
def empty_file(tmp_dir):
    """An empty file for error case testing."""
    f = tmp_dir / "empty.txt"
    f.write_bytes(b"")
    return f


@pytest.fixture
def unsupported_file(tmp_dir):
    """A .docx file to test unsupported format error."""
    f = tmp_dir / "document.docx"
    f.write_bytes(b"fake docx content")
    return f


# ---------------------------------------------------------------------------
# Metadata fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_checksum():
    """A valid SHA-256 checksum for testing."""
    return hashlib.sha256(b"sample content").hexdigest()


@pytest.fixture
def sample_source_url():
    return "https://uaelegislation.gov.ae/en/legislations/3284"


@pytest.fixture
def sample_doc_metadata(sample_checksum, sample_source_url):
    """A pre-built DocumentMetadata instance."""
    from src.ingestion.metadata import (
        DocumentMetadata, DocType, LanguageAuthority, Regulator
    )
    doc_id = DocumentMetadata.generate_doc_id(sample_source_url, sample_checksum)
    return DocumentMetadata(
        doc_id=doc_id,
        title="CBUAE Federal Decree-Law No. 6 of 2025",
        regulator=Regulator.CBUAE,
        doc_type=DocType.FEDERAL_LAW,
        source_url=sample_source_url,
        checksum=sample_checksum,
        effective_date=date(2025, 1, 1),
        in_force=True,
    )
