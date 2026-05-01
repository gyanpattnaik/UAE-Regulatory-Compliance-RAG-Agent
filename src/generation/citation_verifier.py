"""
citation_verifier.py — Post-generation citation integrity checker.

After the LLM returns an Answer, this module verifies that each citation's
exact_quote is actually present in the source chunk text. Citations that fail
verification are flagged, and a composite confidence score is computed from
three independent signals:
  1. Retrieval confidence (from cross-encoder scores)
  2. Citation verification rate (substring matching)
  3. LLM self-reported confidence (least trusted signal)
"""

import logging
from typing import List, Dict, Any

from .schemas import Answer, Citation

logger = logging.getLogger(__name__)

# Weights for composite confidence scoring.
# Retrieval confidence (server-side, trustworthy) gets highest weight.
# LLM self-report gets lowest weight since it's the least reliable signal.
_W_RETRIEVAL = 0.4
_W_CITATION = 0.3
_W_LLM = 0.3


def verify_citations(
    answer: Answer,
    retrieved_chunks: List[Dict[str, Any]],
    retrieval_confidence: float = 0.0,
) -> Answer:
    """
    Verify that each citation's exact_quote exists in the referenced chunk
    and compute a composite confidence score from multiple independent signals.

    Modifies the answer in-place:
    - Appends '[UNVERIFIED]' to explanations of failed citations
    - Sets retrieval_confidence from the retrieval pipeline
    - Computes composite_confidence from three signals
    - Logs verification results

    Args:
        answer: The structured Answer from the LLM.
        retrieved_chunks: The chunks that were passed to the LLM.
        retrieval_confidence: Server-side confidence from cross-encoder scores.

    Returns:
        The same Answer object, with verification results and composite score.
    """
    # Store retrieval confidence on the answer
    answer.retrieval_confidence = retrieval_confidence

    if not answer.citations or answer.answer_mode == "Refuse":
        # For refusals, composite is just retrieval + LLM (no citations to verify)
        answer.composite_confidence = round(
            _W_RETRIEVAL * retrieval_confidence + _W_LLM * answer.confidence_score,
            4
        )
        return answer

    # Build a lookup: chunk_id -> chunk text
    chunk_lookup: Dict[str, str] = {}
    for chunk in retrieved_chunks:
        cid = chunk.get("metadata", {}).get("chunk_id", "")
        if cid:
            chunk_lookup[cid] = chunk.get("text", "")

    verified_count = 0
    total_count = len(answer.citations)

    for citation in answer.citations:
        source_text = chunk_lookup.get(citation.chunk_id, "")

        if not source_text:
            # chunk_id not found in retrieved chunks
            citation.explanation = f"[UNVERIFIED - source chunk not found] {citation.explanation}"
            logger.warning(f"Citation chunk_id '{citation.chunk_id}' not found in retrieved chunks.")
            continue

        # Normalize whitespace for fuzzy matching
        normalized_source = " ".join(source_text.split()).lower()
        normalized_quote = " ".join(citation.exact_quote.split()).lower()

        if normalized_quote in normalized_source:
            verified_count += 1
        else:
            citation.explanation = f"[UNVERIFIED - quote not found in source] {citation.explanation}"
            logger.warning(
                f"Citation quote not found in chunk '{citation.chunk_id[:16]}...': "
                f"'{citation.exact_quote[:50]}...'"
            )

    # Compute citation verification rate
    citation_rate = verified_count / total_count if total_count > 0 else 0.0

    # Compute composite confidence from three independent signals
    composite = (
        _W_RETRIEVAL * retrieval_confidence
        + _W_CITATION * citation_rate
        + _W_LLM * answer.confidence_score
    )
    answer.composite_confidence = round(min(1.0, max(0.0, composite)), 4)

    logger.info(
        f"Confidence breakdown: retrieval={retrieval_confidence:.3f}, "
        f"citation_rate={citation_rate:.3f} ({verified_count}/{total_count}), "
        f"llm={answer.confidence_score:.3f} → composite={answer.composite_confidence:.3f}"
    )

    return answer
