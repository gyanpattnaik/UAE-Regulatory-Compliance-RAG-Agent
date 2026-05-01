"""
test_generation.py — Tests for schemas, prompts, and formatting.
"""

import pytest
from src.generation.schemas import Answer, Citation
from src.generation.prompts import build_user_prompt
from src.generation.formatter import format_answer_markdown, DISCLAIMER


def test_citation_schema():
    """Verify Pydantic validation on Citations."""
    cit = Citation(chunk_id="c1", exact_quote="quote", explanation="exp")
    assert cit.chunk_id == "c1"


def test_answer_schema_validation():
    """Verify Answer validation, particularly confidence score bounds."""
    # Valid
    ans = Answer(
        answer_mode="Extract",
        confidence_score=0.9,
        citations=[],
        final_text="Test"
    )
    assert ans.confidence_score == 0.9

    # Invalid confidence score > 1.0
    with pytest.raises(ValueError):
        Answer(
            answer_mode="Extract",
            confidence_score=1.5,
            citations=[],
            final_text="Test"
        )


def test_build_user_prompt():
    chunks = [
        {"text": "Chunk 1 text", "metadata": {"chunk_id": "c1", "regulator": "CBUAE", "doc_type": "Law"}},
    ]
    prompt = build_user_prompt("What is it?", chunks)
    assert "Chunk 1 text" in prompt
    assert "What is it?" in prompt
    assert "[CHUNK_ID: c1]" in prompt


def test_format_answer_markdown():
    cit = Citation(chunk_id="abcdef_chunk12", exact_quote="This is the law", explanation="It states the law")
    ans = Answer(
        answer_mode="Summarize",
        confidence_score=0.85,
        citations=[cit],
        final_text="Here is the summary."
    )
    
    md = format_answer_markdown(ans)
    
    assert "Here is the summary." in md
    assert "Summarize" in md
    assert "85.0%" in md
    assert "Verified Citations" in md
    assert "This is the law" in md
    assert "abcdef" in md
    assert DISCLAIMER in md


def test_format_answer_markdown_refusal():
    ans = Answer(
        answer_mode="Refuse",
        confidence_score=0.0,
        citations=[],
        final_text="I cannot answer this."
    )
    
    md = format_answer_markdown(ans)
    assert "I cannot answer this." in md
    assert "Verified Citations" not in md
    assert DISCLAIMER in md
