# UAE Regulatory Compliance RAG Agent — Project Tracker

> This document serves as a Notion-ready project tracker. It contains detailed, story-by-story documentation of the build process, capturing technical trade-offs, architecture decisions, and completion status.

---

## 🗂️ Build Step 1: Document Ingestion Pipeline
**Status**: ✅ Completed
**Focus**: Parsing complex regulatory PDFs, structure-aware chunking, and deterministic metadata extraction.

### 📝 Story Description
The first foundational step is to build a high-fidelity ingestion pipeline capable of parsing strict regulatory texts (like CBUAE laws and VARA rulebooks) without losing critical structural context (e.g., Article numbers, Sections, Chapters). The output must be clean, chunked JSON ready for embedding.

### 🛠️ Technical Implementation & Decisions
- **Structure-Aware Parsing**: We implemented `pdfplumber` as the primary parser to extract exact character coordinates, allowing us to accurately identify and preserve headings (e.g., "Article 1", "Chapter II"). `pypdf` was included as a fallback.
- **Deterministic Hashing**: Implemented SHA-256 checksums on raw bytes. We use this to generate deterministic `doc_id` and `chunk_id` values, ensuring idempotency (re-ingesting the same document won't create duplicates in the vector store).
- **Atomic Table Extraction**: Regulatory tables often contain crucial deadlines and thresholds. We built logic to detect `[TABLE]` markers from the parser and treat them as **atomic chunks**—meaning they are never split mid-row, even if they exceed standard token limits.
- **Tiny-Chunk Merging**: During testing, we found that isolating headings into their own chunks created "orphaned" chunks with <20 tokens (e.g., "Article 2 — Definitions"). We added a post-processing pass to merge these tiny slivers into their adjacent text blocks to preserve retrieval context.
- **Pydantic Metadata Validation**: Enforced strict validation for `Regulator` (CBUAE, VARA) and `DocType` (Federal Law, Rulebook, etc.) before any data touches the file system.

### 🧪 Verification & Impact
- Built a robust `pytest` suite with **43 passing tests** across `metadata`, `parser`, `chunker`, and integration `pipeline`.
- Created an interactive `cli.py` to ingest documents via command line and view system health.
- **Result**: Successfully ingested a sample "CBUAE Federal Decree-Law No. 6 of 2025" document. The pipeline correctly extracted 14 cohesive chunks (968 tokens) while preserving table integrity.

---

## 🗂️ Build Step 2: Vector Store & Hybrid Search Pipeline
**Status**: ✅ Completed
**Focus**: Dense embeddings, BM25 lexical search, and Cross-Encoder reranking.

### 📝 Story Description
To maximize retrieval accuracy for strict regulatory questions, a single vector search is not enough. Regulatory answers often depend on exact keyword matches ("Article 14.2", "AML/CFT") which dense vectors can miss, while pure keyword search misses semantic synonyms ("money laundering" vs "illicit finance"). We built a Hybrid Search pipeline combining dense embeddings, sparse lexical search, and a powerful Cross-Encoder reranking model to surface the absolute best chunks for generation.

### 🛠️ Technical Implementation & Decisions
- **Zero-Cost Local Embeddings**: Swapped the originally planned OpenAI embeddings for a local, open-source model (`sentence-transformers/all-MiniLM-L6-v2`). This eliminates API costs for vectorization, enhances privacy, and executes entirely on the local machine via `ChromaDB`.
- **Hybrid Search via RRF**: Implemented parallel retrieval from both ChromaDB (Dense) and `rank-bm25` (Sparse/Lexical). These lists are merged using the Reciprocal Rank Fusion (RRF) algorithm (k=60), ensuring documents that rank highly in *both* methods rise to the top.
- **Cross-Encoder Reranking**: The RRF merged list provides a broad candidate pool. We then pass the top 10-15 chunks to a Cross-Encoder (`ms-marco-MiniLM-L-6-v2`) which scores the exact query against each chunk text simultaneously. This drastically improves precision over bi-encoder similarity.
- **State Management**: ChromaDB handles its own SQLite persistence (`/data/chroma_db`). For BM25, we implemented a custom persistence layer using `pickle` to serialize the inverted index to `/data/indices/bm25_index.pkl`, drastically reducing startup latency for queries.

### 🧪 Verification & Impact
- Built a retrieval CLI to test queries end-to-end (`python -m src.retrieval.cli query "What are the rules?"`).
- All components successfully process the CBUAE sample document, correctly prioritizing sections based on both exact keywords and semantic meaning.
- Completed full Pytest suite for ChromaDB wrappers, BM25 tokenization, and RRF logic with 100% pass rate.

---

## 🗂️ Build Step 3: Answer Generation & Guardrails
**Status**: ✅ Completed
**Focus**: LLM Orchestration, Pydantic Structured Outputs, Quote-Span Citations, and Legal Guardrails.

### 📝 Story Description
A RAG pipeline in the regulatory domain carries high liability risk. If the LLM hallucinates an answer or provides unqualified legal advice, it could cause severe compliance breaches for the user. We needed to strictly constrain the generation phase to force the model to output exact quote-span citations, refuse off-topic questions, and format answers defensively.

### 🛠️ Technical Implementation & Decisions
- **Groq & Llama 3**: We integrated the Groq API utilizing `llama3-70b-8192` for generation. Groq provides ultra-low latency inference, crucial for keeping the RAG pipeline snappy despite the complex validation loops.
- **Structured Outputs (Instructor + Pydantic)**: Instead of parsing raw text, we used the `instructor` library to force the LLM into JSON-mode, strictly adhering to our Pydantic `Answer` schema. This schema demands an `answer_mode`, a `confidence_score` float, and a list of `citations` (each requiring a `chunk_id`, an `exact_quote`, and an `explanation`).
- **Quote-Span Citations**: The prompt architecture strictly prohibits synthesizing rules. Every claim made in the `final_text` must be backed by a character-for-character exact quote from the retrieved context. If the context does not contain the answer, the LLM is forced to output `answer_mode="Refuse"`.
- **Mandatory Legal Disclaimers**: We implemented a `formatter.py` module that programmatically injects a persistent legal disclaimer to the bottom of *every* generated answer, regardless of the LLM's output, ensuring risk mitigation logic is handled in standard code, not prompt engineering.

### 🧪 Verification & Impact
- Built full unit tests covering Pydantic schema validation, prompt generation logic, and the Markdown formatter.
- Created `python -m src.generation.cli ask` to test the full E2E pipeline from terminal query -> Hybrid Search -> Reranker -> LLM Generation -> Formatted Output.
- Validated that the LLM successfully refuses unrelated queries (e.g., "recipe for cake") and correctly cites the CBUAE/VARA test chunks.

---

## 🗂️ Build Step 4: Streamlit Query UI
**Status**: ✅ Completed
**Focus**: User Experience (UX), Citation Rendering, and Session Management.

### 📝 Story Description
The final phase of the MVP was to wrap our robust RAG backend (ChromaDB + BM25 + CrossEncoder + Groq) into an intuitive frontend. Compliance Officers need a tool that feels conversational but exposes the rigorous auditing metrics (Confidence Score, Exact Quotes) immediately. We used Streamlit to rapidly prototype a professional, dark-themed Chat UI.

### 🛠️ Technical Implementation & Decisions
- **Session State Management**: We implemented a persistent chat history using Streamlit's `st.session_state`. This allows the user to review past questions and citations within the same session, mimicking the familiar ChatGPT interface while preserving our strict regulatory guardrails.
- **Visual Citations**: Instead of dumping massive walls of text, we created `render_citations()`. This uses Streamlit Expanders (`st.expander`) to hide the dense "Exact Quote" and "Chunk ID" metadata by default, showing only a clean, 60-character explanation snippet. If an auditor needs to verify a claim, they simply click to expand the full source text.
- **Dynamic Metrics**: We utilized `st.metric()` to display the LLM's **Analysis Mode** (Extract, Summarize, Refuse) alongside its **Confidence Score**. The score is color-coded (Green for High Trust > 75%, Red for Low Trust < 40%) to immediately signal the reliability of the AI's response to the user.
- **Configurable Backend**: The UI includes a sidebar allowing users to dynamically adjust the RAG parameters (filtering by Regulator, adjusting the top-k retrieval count) which directly updates the `HybridRetriever` context pool.

### 🧪 Verification & Impact
- Built `app.py` as the main entry point and successfully routed the `Generator` and `HybridRetriever` outputs to the frontend.
- Validated that the UI correctly handles "Refusal" cases by gracefully degrading the response without crashing the expander components.
- The resulting interface is clean, professional, and ready for deployment or demoing to hiring committees.

---

**🏁 MVP BUILD COMPLETE!**

## 🗂️ Build Step 5: Golden Dataset & Evaluation
**Status**: ✅ Completed
**Focus**: Deterministic Testing, Routing Accuracy, Fact Recall

### 📝 Story Description
A compliance AI is only as good as its measurable accuracy. We needed to definitively prove that our RAG architecture correctly roots out hallucinations and properly refuses adversarial questions. To do this without incurring the massive latency and cost of LLM-as-a-judge frameworks like `ragas`, we built a fast, customized, deterministic evaluation harness.

### 🛠️ Technical Implementation & Decisions
- **Golden Dataset Curation**: We created `data/golden_dataset/eval_set.json` containing a mix of valid extraction queries, summarization queries, and out-of-scope adversarial queries (e.g., asking for cake recipes or legal advice).
- **Custom Evaluation Script**: We built `src/evaluation/evaluate.py` using Python and `rich` for terminal formatting. The script runs the Golden Dataset end-to-end through the `HybridRetriever` and `Generator`.
- **Metrics Calculation**:
  - **Routing Accuracy**: Measures if the LLM correctly chose the expected Answer Mode (Extract, Summarize, Refuse).
  - **Fact Recall**: Deterministically checks if the expected core facts (keywords) are present in the generated string.
  - **Latency**: Measures end-to-end processing time per query.

### 🧪 Verification & Impact
- **Results**: The evaluation harness executed successfully.
- **Routing Accuracy**: **100%**. The system perfectly refused all out-of-scope and adversarial queries, while correctly identifying legitimate regulatory questions.
- **Fact Recall**: **80%**. The system successfully retrieved and cited the correct information from the regulatory chunks for the valid queries.
- **Latency**: **5.3s average** per query. 

---

**🏁 ALL MVP BUILD STEPS COMPLETE! The project is fully documented and ready for portfolio presentation.**
