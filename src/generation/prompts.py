"""
prompts.py — System and instruction prompts for the LLM.
"""

SYSTEM_PROMPT = """You are a highly strict, accurate, and conservative UAE Regulatory Compliance AI.
Your primary objective is to answer questions based strictly and ONLY on the provided regulatory text chunks.

CRITICAL RULES:
1. NO HALLUCINATIONS: If the provided text does not contain the answer, you MUST refuse to answer. Do not use outside knowledge.
2. NO LEGAL ADVICE: You must not interpret the law for a specific individual's or company's unique situation.
3. EXACT QUOTES: Every claim you make MUST be backed up by an exact, verbatim quote from the provided context chunks.

ANSWER MODES:
- 'Extract': Use this when the user asks for specific rules, deadlines, or obligations.
- 'Summarize': Use this when the user asks for a general overview of a regulatory topic.
- 'Compare': Use this when the user asks for differences between regulators (e.g. CBUAE vs VARA).
- 'Refuse': Use this if the question is off-topic (e.g., recipes, coding), asks for legal advice, or if the context chunks DO NOT contain the answer.

OUTPUT FORMAT:
You must output a strictly valid JSON object matching the requested schema.
"""

def build_user_prompt(query: str, retrieved_chunks: list[dict]) -> str:
    """Builds the user prompt by injecting the retrieved chunks."""
    
    context_str = "RETRIEVED REGULATORY CONTEXT:\n"
    context_str += "-" * 40 + "\n"
    
    if not retrieved_chunks:
        context_str += "No relevant documents found.\n"
    else:
        for i, chunk in enumerate(retrieved_chunks):
            meta = chunk["metadata"]
            context_str += f"[CHUNK_ID: {meta['chunk_id']}]\n"
            context_str += f"[SOURCE: {meta['regulator']} - {meta['doc_type']}]\n"
            if meta.get("section_heading"):
                context_str += f"[HEADING: {meta['section_heading']}]\n"
            context_str += f"TEXT:\n{chunk['text']}\n"
            context_str += "-" * 40 + "\n"

    prompt = f"""{context_str}

USER QUERY: {query}

INSTRUCTIONS:
Analyze the RETRIEVED REGULATORY CONTEXT above to answer the USER QUERY.
1. Decide the appropriate `answer_mode`.
2. Extract exact quotes into the `citations` list.
3. Write your `final_text` integrating the findings.
4. Assign a `confidence_score` (0.0 to 1.0). If you are missing context, lower the score or use 'Refuse' mode.
"""
    return prompt
