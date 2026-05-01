"""
test_vector_store.py — Tests for ChromaDB wrapper.
"""

import pytest
from src.retrieval.vector_store import VectorStore


@pytest.fixture
def temp_vector_store():
    vs = VectorStore(ephemeral=True)
    # Clean state
    vs.reset()
    yield vs
    vs.reset()


def test_vector_store_initialization(temp_vector_store):
    assert temp_vector_store.get_document_count() == 0


def test_add_chunks_and_dense_search(temp_vector_store):
    chunks = [
        {
            "text": "Anti-Money Laundering (AML) requires strict KYC.",
            "metadata": {"chunk_id": "c1", "regulator": "CBUAE"}
        },
        {
            "text": "Virtual assets must be registered.",
            "metadata": {"chunk_id": "c2", "regulator": "VARA"}
        }
    ]
    temp_vector_store.add_chunks(chunks)
    assert temp_vector_store.get_document_count() == 2

    # Search for AML
    results = temp_vector_store.dense_search("What are the rules for money laundering?", top_k=1)
    assert len(results) == 1
    assert "AML" in results[0]["text"]
    assert results[0]["metadata"]["chunk_id"] == "c1"


def test_metadata_filtering(temp_vector_store):
    chunks = [
        {
            "text": "Financial reporting is due Q1.",
            "metadata": {"chunk_id": "c1", "regulator": "CBUAE"}
        },
        {
            "text": "Financial reporting for crypto is due Q2.",
            "metadata": {"chunk_id": "c2", "regulator": "VARA"}
        }
    ]
    temp_vector_store.add_chunks(chunks)

    # Search with filter
    results = temp_vector_store.dense_search("financial reporting", top_k=2, filter_dict={"regulator": "VARA"})
    assert len(results) == 1
    assert results[0]["metadata"]["chunk_id"] == "c2"
