"""
hybrid_search.py — Main retrieval orchestrator.

Combines Dense (ChromaDB) and Sparse (BM25) search using
Reciprocal Rank Fusion (RRF), then reranks with a Cross-Encoder.

Returns both the final chunks AND a server-side retrieval_confidence
score derived from cross-encoder scores (not LLM self-report).
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .bm25_index import BM25Index
from .reranker import Reranker
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

# Minimum cross-encoder score to consider a retrieval "confident".
# If the best chunk scores below this, the retrieval is rejected
# server-side before the LLM ever sees the context — preventing
# hallucination on low-relevance matches.
_RETRIEVAL_CONFIDENCE_THRESHOLD = -3.0


@dataclass
class RetrievalResult:
    """Output of the hybrid retrieval pipeline."""
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    retrieval_confidence: float = 0.0
    max_reranker_score: float = 0.0
    rejected: bool = False


def compute_rrf(
    dense_results: List[Dict[str, Any]],
    sparse_results: List[Dict[str, Any]],
    k: int = 60
) -> List[Dict[str, Any]]:
    """
    Compute Reciprocal Rank Fusion (RRF) scores for two ranked lists.
    
    Args:
        dense_results: Results from VectorStore (sorted by distance).
        sparse_results: Results from BM25 (sorted by score).
        k: Smoothing constant for RRF (default 60 is standard in literature).
        
    Returns:
        List of merged unique chunks, sorted by their RRF score descending.
    """
    # Map chunk_id -> chunk data + RRF score
    rrf_map: Dict[str, Dict[str, Any]] = {}

    def _add_to_rrf(results: List[Dict[str, Any]], rank_offset: int = 1):
        for rank, chunk in enumerate(results, start=rank_offset):
            chunk_id = chunk["metadata"]["chunk_id"]
            if chunk_id not in rrf_map:
                # Copy the chunk dictionary so we don't mutate the original
                rrf_map[chunk_id] = {
                    "text": chunk["text"],
                    "metadata": chunk["metadata"],
                    "rrf_score": 0.0,
                    "sources": []
                }
            
            # RRF Formula: 1 / (k + rank)
            rrf_score = 1.0 / (k + rank)
            rrf_map[chunk_id]["rrf_score"] += rrf_score

    _add_to_rrf(dense_results)
    _add_to_rrf(sparse_results)

    # Convert map to list and sort
    merged_results = list(rrf_map.values())
    merged_results.sort(key=lambda x: x["rrf_score"], reverse=True)

    return merged_results


def _compute_retrieval_confidence(reranker_scores: List[float]) -> float:
    """
    Compute a normalised retrieval confidence score from raw cross-encoder scores.

    Cross-encoder scores are unbounded (typically -10 to +10 for ms-marco models).
    We apply a sigmoid-like mapping to normalise into [0, 1]:
      confidence = max_score mapped through a logistic curve centred at 0.
    """
    if not reranker_scores:
        return 0.0

    max_score = max(reranker_scores)

    # Logistic normalisation: score → [0, 1]
    # Centred at 0, steepness factor k=1.5
    import math
    confidence = 1.0 / (1.0 + math.exp(-1.5 * max_score))

    return round(confidence, 4)


class HybridRetriever:
    """Orchestrates Hybrid Search (Dense + Sparse + Reranker)."""

    def __init__(self):
        """Initialize all components of the retrieval pipeline."""
        logger.info("Initializing HybridRetriever components...")
        self.vector_store = VectorStore()
        self.bm25 = BM25Index()
        self.reranker = Reranker()
        logger.info("HybridRetriever ready.")

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Full retrieval pipeline for a user query.
        
        1. Query VectorStore (Dense) -> Top N
        2. Query BM25 (Sparse) -> Top N
        3. Merge via Reciprocal Rank Fusion (RRF) -> Top M
        4. Rerank via Cross-Encoder -> Top K
        5. Compute server-side retrieval confidence
        
        Args:
            query: The user's question.
            top_k: Final number of chunks to return.
            filter_dict: Optional metadata filter (e.g. {"regulator": "CBUAE"}).
            
        Returns:
            List of final selected chunks sorted by relevance.
            Each chunk dict includes a 'retrieval_confidence' key on the first element.
        """
        result = self.retrieve_with_confidence(query, top_k, filter_dict)
        
        # Attach retrieval_confidence to the first chunk for downstream consumption
        if result.chunks and not result.rejected:
            result.chunks[0]["_retrieval_confidence"] = result.retrieval_confidence
            result.chunks[0]["_max_reranker_score"] = result.max_reranker_score
        
        return result.chunks if not result.rejected else []

    def retrieve_with_confidence(
        self,
        query: str,
        top_k: int = 5,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> RetrievalResult:
        """
        Full retrieval pipeline returning structured result with confidence.

        This is the detailed API that returns the RetrievalResult dataclass
        with confidence metadata. The simpler `retrieve()` method wraps this.
        """
        # We fetch more candidates than we need for the final output
        fetch_k = top_k * 3

        logger.debug(f"Executing dense search for: '{query}'")
        dense_res = self.vector_store.dense_search(query, top_k=fetch_k, filter_dict=filter_dict)
        
        logger.debug(f"Executing sparse search for: '{query}'")
        sparse_res = self.bm25.sparse_search(query, top_k=fetch_k, filter_dict=filter_dict)

        logger.debug(f"Merging {len(dense_res)} dense and {len(sparse_res)} sparse results via RRF.")
        fused_res = compute_rrf(dense_res, sparse_res)

        if not fused_res:
            return RetrievalResult(chunks=[], retrieval_confidence=0.0, rejected=True)

        # We pass the top RRF candidates to the heavy Cross-Encoder
        rerank_pool_size = max(top_k * 2, 10)
        candidates = fused_res[:rerank_pool_size]

        logger.debug(f"Reranking top {len(candidates)} candidates.")
        final_chunks, all_scores = self.reranker.rerank(query, candidates, top_k=top_k)

        # Compute server-side retrieval confidence from cross-encoder scores
        retrieval_confidence = _compute_retrieval_confidence(all_scores)
        max_score = max(all_scores) if all_scores else 0.0

        # Server-side rejection: if the best reranker score is below threshold,
        # the context is too weak to generate a reliable answer.
        if max_score < _RETRIEVAL_CONFIDENCE_THRESHOLD:
            logger.warning(
                f"Retrieval rejected: max reranker score {max_score:.3f} "
                f"< threshold {_RETRIEVAL_CONFIDENCE_THRESHOLD}"
            )
            return RetrievalResult(
                chunks=[],
                retrieval_confidence=retrieval_confidence,
                max_reranker_score=max_score,
                rejected=True,
            )

        return RetrievalResult(
            chunks=final_chunks,
            retrieval_confidence=retrieval_confidence,
            max_reranker_score=max_score,
            rejected=False,
        )
