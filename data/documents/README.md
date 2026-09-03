# Evaluation corpus — representative text, not regulatory source

**The five `.txt` files in this directory are synthetic.** They are
representative regulatory text written for this project to exercise and
evaluate the retrieval pipeline. They are **not** verbatim extracts from
any CBUAE or VARA instrument, and must not be relied on for compliance.

Each file is 70–100 lines. Real CBUAE circulars and VARA rulebooks run to
hundreds of pages.

## Why synthetic

The engineering claim this project makes is about retrieval quality —
structure-aware chunking, hybrid dense/sparse search with RRF fusion,
cross-encoder reranking, and post-generation citation verification. A
compact, structurally realistic corpus with a matched golden dataset tests
that claim directly and keeps the repo cloneable without redistributing
copyrighted regulatory text.

## What is real

The regulatory *landscape* described in [`docs/PRD.md`](../../docs/PRD.md)
is real and sourced — Federal Decree-Law No. 6 of 2025, the SCA→CMA
transition under Federal Decree-Law No. 32 of 2025, VARA's rulebook
revisions, and the DFSA thematic review all link to primary sources.

The `source_url` on each document in
[`ingest_all.py`](../../ingest_all.py) points at the **real regulator
landing page for that subject area**, so a reader can reach authoritative
text. It does not point at a specific instrument, because these documents
do not reproduce one.

## Instrument numbers deliberately omitted

Earlier versions of two files carried specific circular numbers that do not
match the real instruments:

| File | Previously claimed | Actual instrument |
|---|---|---|
| `cbuae_aml_circular_3_2025.txt` | "Circular No. 3/2025 — AML" | CBUAE **C 03/2025 is the Open Finance Regulation** (issued 10 July 2025). 2025 AML material sits in Cabinet Resolution No. 134 of 2025 and CBUAE guidance |
| `cbuae_consumer_protection_reg_2025.txt` | "Regulation No. 1/2025" | Consumer Protection Regulation is **Circular No. 8/2020** (31 December 2020) |

Titles now describe subject matter without asserting an instrument number.
Filenames are unchanged to avoid breaking the ingestion manifest and
golden dataset; the number in a filename is historical, not a claim.

## If you want to run this against real documents

Replace these files with genuine PDFs or text, update the `DOCUMENTS`
manifest in `ingest_all.py` with real titles, `source_url`s and effective
dates, and rebuild the golden dataset in
[`../golden_dataset/eval_set.json`](../golden_dataset/eval_set.json) —
the 20 questions are written against *this* corpus and will not measure
anything meaningful against a different one.
