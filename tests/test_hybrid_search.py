"""
test_hybrid_search.py — Tests for BM25, Reranker, and RRF logic.
"""

from src.retrieval.bm25_index import BM25Index, _tokenize
from src.retrieval.hybrid_search import compute_rrf


def test_tokenize():
    text = "The CBUAE (Central Bank) requires AML/CFT compliance!"
    tokens = _tokenize(text)
    assert "cbuae" in tokens
    assert "aml" in tokens
    assert "cft" in tokens
    assert "the" in tokens


def test_bm25_build_and_search(tmp_dir):
    bm25 = BM25Index(persist_dir=str(tmp_dir))
    chunks = [
        {"text": "Apple is a fruit.", "metadata": {"id": 1}},
        {"text": "Banana is also a fruit.", "metadata": {"id": 2}},
        {"text": "A compliance document.", "metadata": {"id": 3, "regulator": "CBUAE"}},
    ]
    bm25.build_index(chunks)
    assert bm25.get_document_count() == 3
    
    # Exact keyword match
    results = bm25.sparse_search("banana", top_k=1)
    assert len(results) == 1
    assert results[0]["metadata"]["id"] == 2

    # Filter
    results = bm25.sparse_search("compliance", top_k=5, filter_dict={"regulator": "CBUAE"})
    assert len(results) == 1
    assert results[0]["metadata"]["id"] == 3


def test_bm25_save_and_load(tmp_dir):
    bm25 = BM25Index(persist_dir=str(tmp_dir))
    chunks = [
        {"text": "Hello world.", "metadata": {"id": 1}},
        {"text": "Unrelated document.", "metadata": {"id": 2}},
        {"text": "Another unrelated one.", "metadata": {"id": 3}}
    ]
    bm25.build_index(chunks)
    bm25.save()

    # Load into a new instance
    bm25_new = BM25Index(persist_dir=str(tmp_dir))
    assert bm25_new.get_document_count() == 3
    res = bm25_new.sparse_search("world", top_k=1)
    assert len(res) == 1


def test_compute_rrf():
    # Dense results (e.g. from vector search)
    dense = [
        {"text": "A", "metadata": {"chunk_id": "1"}},  # rank 1
        {"text": "B", "metadata": {"chunk_id": "2"}},  # rank 2
        {"text": "C", "metadata": {"chunk_id": "3"}},  # rank 3
    ]
    # Sparse results (e.g. from BM25)
    sparse = [
        {"text": "C", "metadata": {"chunk_id": "3"}},  # rank 1
        {"text": "A", "metadata": {"chunk_id": "1"}},  # rank 2
        {"text": "D", "metadata": {"chunk_id": "4"}},  # rank 3
    ]

    # k=60
    # doc 1: 1/(60+1) + 1/(60+2) = 1/61 + 1/62 = 0.01639 + 0.01612 = 0.0325
    # doc 3: 1/(60+3) + 1/(60+1) = 1/63 + 1/61 = 0.01587 + 0.01639 = 0.0322
    # doc 2: 1/(60+2) + 0        = 0.01612
    # doc 4: 0 + 1/(60+3)        = 0.01587
    
    merged = compute_rrf(dense, sparse, k=60)
    
    assert len(merged) == 4
    assert merged[0]["metadata"]["chunk_id"] == "1"
    assert merged[1]["metadata"]["chunk_id"] == "3"
    assert merged[2]["metadata"]["chunk_id"] == "2"
    assert merged[3]["metadata"]["chunk_id"] == "4"
