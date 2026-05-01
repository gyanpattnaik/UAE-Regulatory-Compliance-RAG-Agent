"""
generator.py — LLM orchestrator using Groq and Instructor for structured outputs.

Design: The Groq client is initialised inside Generator.__init__ (not at module
level) to support dependency injection in tests and avoid global mutable state.
"""

import logging
import os
from typing import List, Dict, Any, Optional

from .schemas import Answer
from .prompts import SYSTEM_PROMPT, build_user_prompt

logger = logging.getLogger(__name__)


class Generator:
    """Handles prompt construction and structured generation via Groq."""

    def __init__(
        self,
        model: Optional[str] = None,
        client: Optional[Any] = None,
    ):
        """
        Args:
            model: LLM model name. Defaults to LLM_MODEL env var or llama-3.3-70b-versatile.
            client: Pre-configured instructor client (for dependency injection in tests).
                    If None, a real Groq client is created from GROQ_API_KEY.
        """
        self.model = model or os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

        if client is not None:
            # Dependency injection path — used in tests
            self.client = client
        else:
            # Production path — create real Groq client
            self.client = self._create_client()

    @staticmethod
    def _create_client():
        """Create an instructor-wrapped Groq client from environment variables."""
        try:
            from groq import Groq
            import instructor

            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                logger.warning("GROQ_API_KEY is not set in the environment.")
                return None
            return instructor.from_groq(Groq(api_key=api_key))
        except Exception as e:
            logger.error(f"Failed to initialize Groq client: {e}")
            return None

    def generate_answer(self, query: str, retrieved_chunks: List[Dict[str, Any]]) -> Answer:
        """
        Generates a structured answer from the LLM based on retrieved chunks.
        
        Args:
            query: The user's question.
            retrieved_chunks: List of chunks from the HybridRetriever.
            
        Returns:
            An Answer Pydantic object containing mode, score, citations, and text.
        """
        if not self.client:
            raise ValueError("Groq client is not initialized. Check GROQ_API_KEY.")

        user_prompt = build_user_prompt(query, retrieved_chunks)
        
        logger.info(f"Generating answer using {self.model}...")

        try:
            # We use instructor to force the output into our Answer schema
            answer: Answer = self.client.chat.completions.create(
                model=self.model,
                response_model=Answer,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0, # Zero temperature for maximum determinism and strictness
                max_tokens=2048,
            )
            return answer
        except Exception as e:
            logger.error(f"Error during LLM generation: {e}")
            # Fallback safe response if API fails
            return Answer(
                answer_mode="Refuse",
                confidence_score=0.0,
                citations=[],
                final_text=f"System Error: Failed to generate response. ({str(e)})"
            )
