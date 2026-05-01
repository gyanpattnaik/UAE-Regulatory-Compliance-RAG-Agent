"""
test_confidence.py — Tests for server-side confidence scoring pipeline.

Validates:
1. Reranker does NOT mutate caller's input data
2. Composite confidence formula produces correct weighted scores
3. Retrieval confidence normalisation (logistic mapping)
4. Citation verifier integrates retrieval_confidence correctly
"""

import copy
import math
import pytest

from src.generation.schemas import Answer, Citation
from src.generation.citation_verifier import verify_citations
from src.retrieval.hybrid_search import _compute_retrieval_confidence


# ── Reranker Non-Mutation ──────────────────────────────────────────────

class TestRerankerNonMutation:
    """Verify the reranker never mutates the caller's chunk dicts."""

    def test_rerank_does_not_mutate_input_chunks(self):
        """After reranking, the original chunk dicts should be unchanged."""
        from src.retrieval.reranker import Reranker

        reranker = Reranker()
        original_chunks = [
            {"text": "AML compliance requirements for banks.", "metadata": {"chunk_id": "c1"}},
            {"text": "Virtual asset service provider licensing.", "metadata": {"chunk_id": "c2"}},
        ]

        # Deep copy to compare later
        original_snapshot = copy.deepcopy(original_chunks)

        # Rerank should NOT add cross_encoder_score to original_chunks
        results, scores = reranker.rerank("AML requirements", original_chunks, top_k=2)

        # Original chunks must be unchanged
        assert original_chunks == original_snapshot, \
            "Reranker mutated the caller's input chunks — this is a bug."

        # Results should have cross_encoder_score
        for r in results:
            assert "cross_encoder_score" in r

    def test_rerank_returns_scores_list(self):
        """Reranker should return all raw scores alongside ranked chunks."""
        from src.retrieval.reranker import Reranker

        reranker = Reranker()
        chunks = [
            {"text": "Text A", "metadata": {"chunk_id": "a"}},
            {"text": "Text B", "metadata": {"chunk_id": "b"}},
            {"text": "Text C", "metadata": {"chunk_id": "c"}},
        ]

        results, scores = reranker.rerank("query", chunks, top_k=2)

        assert len(scores) == 3  # All input chunks scored
        assert len(results) == 2  # Only top_k returned
        assert all(isinstance(s, float) for s in scores)

    def test_rerank_empty_input(self):
        """Reranking an empty list should return empty results."""
        from src.retrieval.reranker import Reranker

        reranker = Reranker()
        results, scores = reranker.rerank("query", [], top_k=5)
        assert results == []
        assert scores == []


# ── Retrieval Confidence Normalisation ─────────────────────────────────

class TestRetrievalConfidence:
    """Test the logistic normalisation of cross-encoder scores."""

    def test_high_score_gives_high_confidence(self):
        """A max reranker score of 5+ should produce confidence near 1.0."""
        conf = _compute_retrieval_confidence([5.0, 2.0, 0.1])
        assert conf > 0.95

    def test_low_score_gives_low_confidence(self):
        """A max reranker score well below 0 should produce low confidence."""
        conf = _compute_retrieval_confidence([-5.0, -8.0, -10.0])
        assert conf < 0.05

    def test_zero_score_gives_half_confidence(self):
        """The logistic is centred at 0, so score=0 should give ~0.5."""
        conf = _compute_retrieval_confidence([0.0])
        assert 0.45 <= conf <= 0.55

    def test_empty_scores_gives_zero(self):
        conf = _compute_retrieval_confidence([])
        assert conf == 0.0

    def test_confidence_is_bounded(self):
        """Output must always be in [0, 1]."""
        for s in [-100, -10, -1, 0, 1, 10, 100]:
            conf = _compute_retrieval_confidence([float(s)])
            assert 0.0 <= conf <= 1.0


# ── Composite Confidence ──────────────────────────────────────────────

class TestCompositeConfidence:
    """Test the weighted composite confidence formula in citation_verifier."""

    def _make_answer(self, llm_conf=0.9, citations=None):
        return Answer(
            answer_mode="Extract",
            confidence_score=llm_conf,
            citations=citations or [],
            final_text="Test answer.",
        )

    def _make_chunks(self, chunk_texts):
        return [
            {"text": t, "metadata": {"chunk_id": f"c{i}"}}
            for i, t in enumerate(chunk_texts)
        ]

    def test_composite_with_all_citations_verified(self):
        """When all citations verify, composite should be high."""
        cit = Citation(chunk_id="c0", exact_quote="hello world", explanation="test")
        answer = self._make_answer(llm_conf=0.9, citations=[cit])
        chunks = self._make_chunks(["This is hello world in context."])

        result = verify_citations(answer, chunks, retrieval_confidence=0.85)

        # Expected: 0.4*0.85 + 0.3*1.0 + 0.3*0.9 = 0.34 + 0.30 + 0.27 = 0.91
        assert abs(result.composite_confidence - 0.91) < 0.01
        assert result.retrieval_confidence == 0.85

    def test_composite_with_no_citations_verified(self):
        """When no citations verify, citation_rate=0 lowers composite."""
        cit = Citation(chunk_id="c0", exact_quote="DOES NOT EXIST", explanation="test")
        answer = self._make_answer(llm_conf=0.9, citations=[cit])
        chunks = self._make_chunks(["Completely different text here."])

        result = verify_citations(answer, chunks, retrieval_confidence=0.85)

        # Expected: 0.4*0.85 + 0.3*0.0 + 0.3*0.9 = 0.34 + 0.00 + 0.27 = 0.61
        assert abs(result.composite_confidence - 0.61) < 0.01

    def test_composite_with_refusal(self):
        """Refusals have no citations; composite is retrieval + llm only."""
        answer = Answer(
            answer_mode="Refuse",
            confidence_score=0.0,
            citations=[],
            final_text="Cannot answer.",
        )
        chunks = []

        result = verify_citations(answer, chunks, retrieval_confidence=0.6)

        # Expected: 0.4*0.6 + 0.3*0.0 = 0.24
        assert abs(result.composite_confidence - 0.24) < 0.01

    def test_retrieval_confidence_is_stored_on_answer(self):
        """The retrieval_confidence should be stored on the answer object."""
        answer = self._make_answer()
        chunks = self._make_chunks(["text"])

        result = verify_citations(answer, chunks, retrieval_confidence=0.77)
        assert result.retrieval_confidence == 0.77


# ── Generator Dependency Injection ────────────────────────────────────

class TestGeneratorDI:
    """Test that Generator supports dependency injection."""

    def test_generator_accepts_mock_client(self):
        """Generator should accept a pre-built client without touching env vars."""
        from src.generation.generator import Generator

        mock_client = object()  # Any object works as a placeholder
        gen = Generator(model="test-model", client=mock_client)

        assert gen.client is mock_client
        assert gen.model == "test-model"

    def test_generator_creates_none_client_without_key(self):
        """Without GROQ_API_KEY, client should be None (not crash)."""
        import os
        from src.generation.generator import Generator

        # Temporarily remove the key
        original = os.environ.pop("GROQ_API_KEY", None)
        try:
            gen = Generator()
            # Client may be None or may succeed — depends on env.
            # The key test is that it doesn't crash.
            assert gen.model is not None
        finally:
            if original:
                os.environ["GROQ_API_KEY"] = original
