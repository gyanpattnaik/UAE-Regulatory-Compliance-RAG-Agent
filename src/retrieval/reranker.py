"""
reranker.py — Cross-Encoder reranking for retrieval pipeline.

Re-scores the top-N results from the hybrid search using a powerful
Cross-Encoder model, which evaluates the exact query-document pair.

Design note: this module never mutates the caller's data. All chunk
dicts are deep-copied before scoring so upstream references stay clean.
"""

import copy
import logging
from typing import Any, Dict, List, Tuple

from sentence_transformers import CrossEncoder

logger = logging.getLogger(__name__)


class Reranker:
    """Uses a Cross-Encoder to re-rank candidate chunks."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """Initialize the cross-encoder model."""
        self.model_name = model_name
        logger.info(f"Loading CrossEncoder model: {self.model_name}")
        self.model = CrossEncoder(self.model_name)
        logger.info("CrossEncoder model loaded successfully.")

    def rerank(
        self,
        query: str,
        chunks: List[Dict[str, Any]],
        top_k: int = 5,
    ) -> Tuple[List[Dict[str, Any]], List[float]]:
        """
        Re-rank a list of candidate chunks against the query.

        Args:
            query: The search query string.
            chunks: List of candidate chunks (each must have a 'text' key).
            top_k: Number of top results to return after reranking.

        Returns:
            Tuple of:
              - List of chunk copies sorted by Cross-Encoder score descending.
              - List of all raw cross-encoder scores (for confidence calculation).
        """
        if not chunks:
            return [], []

        # Prepare pairs for the cross-encoder
        pairs = [[query, chunk["text"]] for chunk in chunks]

        # Calculate scores
        raw_scores = self.model.predict(pairs)
        all_scores = [float(s) for s in raw_scores]

        # Create scored copies — never mutate the caller's dicts
        scored_chunks = []
        for i, chunk in enumerate(chunks):
            scored = copy.deepcopy(chunk)
            scored["cross_encoder_score"] = all_scores[i]
            scored_chunks.append(scored)

        # Sort descending by cross-encoder score
        scored_chunks.sort(key=lambda x: x["cross_encoder_score"], reverse=True)

        return scored_chunks[:top_k], all_scores
