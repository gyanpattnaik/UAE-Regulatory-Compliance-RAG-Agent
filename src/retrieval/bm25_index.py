"""
bm25_index.py — Lexical (Sparse) retrieval using rank-bm25.

Provides exact-keyword match capabilities, complementing the dense embeddings.
Maintains an in-memory index that can be serialized to disk.
"""

import logging
import os
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

_INDICES_DIR = os.getenv("INDICES_DIR", "./data/indices")
_BM25_INDEX_FILE = "bm25_index.pkl"


def _tokenize(text: str) -> List[str]:
    """
    Simple word tokenizer for BM25.
    Lowercases and splits on non-alphanumeric characters.
    """
    if not text:
        return []
    return [word for word in re.split(r"\W+", text.lower()) if word]


class BM25Index:
    """Manages the BM25 lexical search index."""

    def __init__(self, persist_dir: str = _INDICES_DIR):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.persist_dir / _BM25_INDEX_FILE
        
        self.bm25: Optional[BM25Okapi] = None
        self.corpus_chunks: List[Dict[str, Any]] = []
        
        self.load()

    def build_index(self, chunks: List[Dict[str, Any]]) -> None:
        """
        Build the BM25 index from scratch using the provided chunks.
        
        Args:
            chunks: List of dicts, each containing 'text' and 'metadata'.
        """
        if not chunks:
            logger.warning("No chunks provided to build BM25 index.")
            return

        self.corpus_chunks = chunks
        tokenized_corpus = [_tokenize(chunk["text"]) for chunk in chunks]
        self.bm25 = BM25Okapi(tokenized_corpus)
        logger.info(f"Built BM25 index with {len(chunks)} chunks.")

    def save(self) -> None:
        """Serialize the index and corpus to disk."""
        if not self.bm25 or not self.corpus_chunks:
            logger.warning("Cannot save empty BM25 index.")
            return

        state = {
            "bm25": self.bm25,
            "corpus_chunks": self.corpus_chunks
        }
        with open(self.index_path, "wb") as f:
            pickle.dump(state, f)
        logger.info(f"Saved BM25 index to {self.index_path}")

    def load(self) -> bool:
        """Load the index and corpus from disk if they exist."""
        if not self.index_path.exists():
            return False

        try:
            with open(self.index_path, "rb") as f:
                state = pickle.load(f)
            self.bm25 = state["bm25"]
            self.corpus_chunks = state["corpus_chunks"]
            logger.info(f"Loaded BM25 index with {len(self.corpus_chunks)} chunks.")
            return True
        except Exception as e:
            logger.error(f"Failed to load BM25 index: {e}")
            return False

    def sparse_search(self, query: str, top_k: int = 10, filter_dict: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Perform a lexical search using BM25.
        
        Args:
            query: The search query string.
            top_k: Number of results to retrieve.
            filter_dict: Optional metadata filter (e.g., {"regulator": "CBUAE"}).
                         BM25 filters *after* scoring for simplicity in this MVP.
            
        Returns:
            List of dicts containing the document text, metadata, and score.
        """
        if not self.bm25 or not self.corpus_chunks:
            logger.warning("BM25 index is empty. Please build the index first.")
            return []

        tokenized_query = _tokenize(query)
        # Get raw scores for all documents in the corpus
        scores = self.bm25.get_scores(tokenized_query)

        results = []
        for i, score in enumerate(scores):
            if score > 0:
                chunk = self.corpus_chunks[i]
                
                # Apply metadata filtering if specified
                if filter_dict:
                    meta = chunk.get("metadata", {})
                    match = all(meta.get(k) == v for k, v in filter_dict.items())
                    if not match:
                        continue
                
                results.append({
                    "text": chunk["text"],
                    "metadata": chunk["metadata"],
                    "score": score  # Higher is better for BM25
                })

        # Sort by score descending and take top_k
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_document_count(self) -> int:
        return len(self.corpus_chunks)
