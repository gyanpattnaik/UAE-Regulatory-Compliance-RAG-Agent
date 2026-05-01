"""
vector_store.py — ChromaDB wrapper for dense retrieval.

Manages the vector database and dense embeddings using a local
SentenceTransformer model (all-MiniLM-L6-v2) for free, private embeddings.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.utils import embedding_functions
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db")
_COLLECTION_NAME = "uae_regulations"


class VectorStore:
    """Wrapper around ChromaDB for dense retrieval of regulatory chunks."""

    def __init__(self, persist_dir: str = _CHROMA_PERSIST_DIR, ephemeral: bool = False):
        """Initialize ChromaDB client and local embedding function."""
        if ephemeral:
            self.client = chromadb.EphemeralClient()
            logger.info("Using ephemeral ChromaDB client for testing.")
        else:
            self.persist_dir = Path(persist_dir)
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(self.persist_dir))
            logger.info(f"VectorStore initialized at {self.persist_dir} (Collection: {_COLLECTION_NAME})")
        
        # Free local embeddings via SentenceTransformers
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        
        self.collection = self.client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=self.embedding_fn,
            metadata={"description": "Dense vectors for UAE regulatory documents"}
        )


    def add_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        """
        Add parsed document chunks to the vector store.
        
        Args:
            chunks: List of dicts, each containing:
                - text: The text chunk.
                - metadata: Dict of metadata (must be primitive types).
        """
        if not chunks:
            return

        # Prepare batches for ChromaDB
        ids = []
        documents = []
        metadatas = []

        for chunk in chunks:
            meta = chunk["metadata"]
            # ChromaDB requires string IDs
            ids.append(meta["chunk_id"])
            documents.append(chunk["text"])
            
            # Ensure metadata values are primitive
            clean_meta = {}
            for k, v in meta.items():
                if v is None:
                    continue
                if isinstance(v, (str, int, float, bool)):
                    clean_meta[k] = v
                else:
                    clean_meta[k] = str(v)
            metadatas.append(clean_meta)

        # Upsert allows re-ingestion of the same document to overwrite old chunks
        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas
        )
        logger.info(f"Upserted {len(ids)} chunks to VectorStore.")

    def dense_search(self, query: str, top_k: int = 10, filter_dict: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Perform a dense vector search for the given query.
        
        Args:
            query: The search query string.
            top_k: Number of results to retrieve.
            filter_dict: Optional metadata filter for ChromaDB.
            
        Returns:
            List of dicts containing the document text, metadata, and distance.
        """
        query_kwargs = {
            "query_texts": [query],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"]
        }
        
        if filter_dict:
            query_kwargs["where"] = filter_dict

        results = self.collection.query(**query_kwargs)

        search_results = []
        if not results["documents"] or not results["documents"][0]:
            return search_results

        # Chroma returns lists of lists (one per query text)
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = results["distances"][0] if results["distances"] else [0.0] * len(docs)

        for doc, meta, dist in zip(docs, metas, dists):
            search_results.append({
                "text": doc,
                "metadata": meta,
                "distance": dist  # Lower is better (typically L2 or cosine distance)
            })

        return search_results

    def get_document_count(self) -> int:
        """Return the total number of chunks in the collection."""
        return self.collection.count()

    def reset(self) -> None:
        """Delete the entire collection (useful for testing)."""
        self.client.delete_collection(_COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=_COLLECTION_NAME,
            embedding_function=self.embedding_fn
        )


