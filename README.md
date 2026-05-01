<div align="center">

# 🏛️ UAE Regulatory Compliance RAG Agent

### Ask a question. Get a cited, verified answer from actual regulatory text.

*No hallucinations. No legal hand-waving. Just source-backed compliance intelligence.*

<br>

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Llama 3.3 70B](https://img.shields.io/badge/LLM-Llama_3.3_70B-FF6B35?style=for-the-badge&logo=meta&logoColor=white)](https://groq.com)
[![Tests](https://img.shields.io/badge/Tests-69_Passing-2EA44F?style=for-the-badge&logo=pytest&logoColor=white)](#-evaluation--metrics)
[![Citation Rate](https://img.shields.io/badge/Citation_Verification-100%25-00D4FF?style=for-the-badge)](#-evaluation--metrics)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

</div>

---

## The Problem

UAE fintech is booming — **1,100+ active licenses** and growing. Every one of those companies has a compliance team manually searching dense legal PDFs from multiple regulators (CBUAE for banking, VARA for crypto). A single cross-regulator question — *"Can we process crypto-to-fiat under our current license?"* — takes **3-4 hours** of research across 5+ documents.

Existing tools either give you keyword search (useless for intent) or ChatGPT-style answers (dangerous without citations). Neither works when the penalty for a wrong answer is **AED 50 million** and a revoked license.

## The Solution

A multi-document RAG agent that actually earns trust. It retrieves relevant regulatory text, generates cited answers with exact quotes, then **verifies every citation server-side** before showing you the result. When it doesn't know, it says so — because in compliance, silence is safer than confidence.

---

## ✨ What Makes This Different

<table>
<tr>
<td width="33%" align="center">
<h3>🔒 Three Layers of Trust</h3>
<p>Cross-encoder reranking → Citation verification → Composite confidence scoring. The LLM never grades itself.</p>
</td>
<td width="33%" align="center">
<h3>🚫 Smart Refusal</h3>
<p>Queries with weak retrieval are rejected <em>before the LLM sees them</em>. Server-side threshold, not prompt-and-pray.</p>
</td>
<td width="33%" align="center">
<h3>📊 Honest Metrics</h3>
<p>93% fact recall, 100% citation verification — measured on 20 real questions, not cherry-picked demos.</p>
</td>
</tr>
</table>

---

## 🛠️ Tech Stack

| Layer | Technology | Why This |
|-------|-----------|----------|
| **LLM** | Groq → Llama 3.3 70B | Fast inference, structured output quality, no vendor lock-in |
| **Embeddings** | all-MiniLM-L6-v2 | Local, free, no API calls — privacy-first |
| **Reranker** | ms-marco-MiniLM-L-6-v2 | Cross-encoder precision for legal text where context matters |
| **Vector DB** | ChromaDB | Persistent, local, zero infrastructure |
| **Sparse Search** | BM25 (rank-bm25) | Catches exact legal terms that embeddings miss |
| **Structured Output** | Instructor + Pydantic | Forces LLM into strict typed schemas — no parsing failures |
| **UI** | Streamlit | Dark mode, session persistence, rapid iteration |

---

## 🏗️ How It Works

```
                    ┌─────────────────────────────────────────────┐
                    │              USER QUERY                     │
                    └────────────────┬────────────────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │         HYBRID RETRIEVAL         │
                    │                                  │
                    │  Dense (ChromaDB) ──┐            │
                    │                     ├─► RRF Merge│
                    │  Sparse (BM25)  ────┘            │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │     CROSS-ENCODER RERANKER       │
                    │                                  │
                    │  Score < threshold? ──► REJECT   │
                    │  Score ≥ threshold? ──► PASS     │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │      LLM GENERATION (Groq)      │
                    │                                  │
                    │  Pydantic schema enforcement     │
                    │  Temperature = 0 (deterministic) │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │    CITATION VERIFICATION         │
                    │                                  │
                    │  Substring match every quote     │
                    │  against source chunk text       │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │    COMPOSITE CONFIDENCE          │
                    │                                  │
                    │  40% retrieval + 30% citation    │
                    │  + 30% LLM → single score        │
                    └────────────────┬────────────────┘
                                     │
                    ┌────────────────▼────────────────┐
                    │         STREAMLIT UI             │
                    └─────────────────────────────────┘
```

**Key design choice:** Contextual enrichment — chunks are prefixed with `[Regulator | Doc Title | Section]` before embedding, so the dense model can distinguish similar text from different regulatory bodies. Raw text is preserved separately for citation verification.

---

## 📊 Evaluation & Metrics

Evaluated against a **20-question golden dataset** — 15 substantive regulatory questions + 5 adversarial (recipes, coding requests, off-topic).

| Metric | Result | What It Means |
|--------|--------|---------------|
| **Routing Accuracy** | 100% (20/20) | Correctly classifies Extract / Summarize / Compare / Refuse |
| **Fact Recall** | 93.3% (15 questions) | Key regulatory facts surfaced in the answer |
| **Citation Verification** | 100% (15 answers) | Every LLM-generated quote exists in the source text |
| **Unit Tests** | 69 passing | Covers schemas, retrieval, chunking, confidence, DI |

> *The evaluation math only counts substantive questions for fact recall — adversarial refusals don't inflate the average. We measure honestly.*

---

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/YOUR_USERNAME/UAE-Regulatory-Compliance-RAG-Agent.git
cd UAE-Regulatory-Compliance-RAG-Agent
python -m venv venv && venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Add your GROQ_API_KEY to .env
```

### 3. Ingest documents

```bash
python ingest_all.py
```
This processes 5 regulatory documents → 38 chunks → ChromaDB + BM25 indexes.

### 4. Launch

```bash
python -m streamlit run app.py
```

### 5. Run tests

```bash
python -m pytest tests/ -v
```

### 6. Run evaluation

```bash
python -m src.evaluation.evaluate
```

---

## 📂 Project Structure

```
├── app.py                          # Streamlit UI entry point
├── ingest_all.py                   # Document ingestion with contextual enrichment
├── src/
│   ├── ingestion/
│   │   ├── parser.py               # PDF/TXT structure extraction
│   │   ├── chunker.py              # Structure-aware chunking (heading-split + overlap)
│   │   ├── metadata.py             # Document & chunk metadata schemas
│   │   └── pipeline.py             # End-to-end ingestion orchestrator
│   ├── retrieval/
│   │   ├── vector_store.py         # ChromaDB dense retrieval
│   │   ├── bm25_index.py           # BM25 sparse retrieval
│   │   ├── hybrid_search.py        # RRF fusion + confidence threshold
│   │   └── reranker.py             # Cross-encoder reranking (non-mutating)
│   ├── generation/
│   │   ├── generator.py            # Groq LLM orchestrator (DI-ready)
│   │   ├── schemas.py              # Pydantic output models + composite confidence
│   │   ├── citation_verifier.py    # Post-generation quote verification
│   │   ├── prompts.py              # System & user prompt templates
│   │   └── formatter.py            # Markdown output formatting
│   ├── evaluation/
│   │   └── evaluate.py             # Golden dataset evaluation harness
│   └── ui/
│       └── components.py           # Streamlit metric & citation renderers
├── data/
│   ├── documents/                  # 5 source regulatory texts
│   └── golden_dataset/
│       └── eval_set.json           # 20-question evaluation dataset
├── tests/                          # 69 tests (unit + integration)
├── docs/
│   └── PRD.md                      # Full Product Requirements Document
├── requirements.txt
└── pyproject.toml
```

---

## 🧠 Design Decisions FAQ

<details>
<summary><strong>Why hybrid search instead of just embeddings?</strong></summary>
<br>
Regulatory text has a unique failure mode: exact legal identifiers. A query about "Article 42(3)(a) penalties" gets generic embedding similarity from the dense model, but BM25 catches the exact string. Conversely, "What are the money laundering reporting timelines?" needs semantic matching because the source text says "SAR filing deadlines." RRF fusion gives us both.
</details>

<details>
<summary><strong>Why not just let the LLM report its own confidence?</strong></summary>
<br>
Because it lies. LLM self-reported confidence is essentially "vibes in JSON" — the model outputs 0.95 even when the retrieved context is barely relevant. We replaced it with a composite score: 40% retrieval confidence (from cross-encoder scores), 30% citation verification rate (server-side substring matching), 30% LLM self-report. Three independent signals, weighted by trustworthiness.
</details>

<details>
<summary><strong>Why not use LangChain or LlamaIndex?</strong></summary>
<br>
Citation verification requires access to the exact chunk text that was passed to the LLM — frameworks abstract this away. Composite confidence requires raw cross-encoder scores from the reranking step — frameworks don't expose these. When debugging why a citation failed, we need to trace: BM25 score → RRF rank → reranker score → chunk text → LLM quote → substring match. That traceability disappears behind framework abstractions.
</details>

<details>
<summary><strong>What happens when the system doesn't know the answer?</strong></summary>
<br>
Two safety nets. First, the prompt instructs the LLM to refuse when context is insufficient. Second — and more importantly — a server-side retrieval confidence threshold rejects queries where the best cross-encoder score is too low, <em>before the LLM ever sees the context</em>. The system says "I don't know" at the infrastructure level, not just the prompt level.
</details>

---

## 🗺️ Roadmap

```
 ✅ Done                    🔨 Next                     🔮 Future
─────────────────     ─────────────────────     ────────────────────
 Multi-doc corpus      Real PDF ingestion        Multi-language (AR)
 Hybrid search+RRF     User PDF upload           Version-pinned queries
 Citation verifier     Semantic similarity        Regulatory diff alerts
 Composite confidence  verification (V2)         GRC platform API
 69 passing tests      Expanded eval (500+ Qs)   Fine-tuned embeddings
 Contextual enrichment Audit trail database      DFSA/ADGM expansion
```

---

## 🔒 Safety & Guardrails

Every answer includes a **mandatory legal disclaimer**. The system prompt forbids legal advice. The Pydantic schema enforces a `Refuse` mode for off-topic or advisory queries. Server-side retrieval thresholds reject weak context. Citation verification catches fabricated quotes. `.env` is gitignored, and `.env.example` provides a safe template.

**This is a portfolio demonstration system, not a production compliance platform.**

---

## 🙏 Acknowledgements

- **[@MousumiMohapatra08](https://github.com/MousumiMohapatra08)** :- Project concept and direction

---

<div align="center">

*Built with obsessive attention to trust, safety, and honest measurement.*

**If you found this useful, consider giving it a ⭐**

</div>
