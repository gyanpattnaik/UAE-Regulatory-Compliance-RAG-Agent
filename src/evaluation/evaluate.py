"""
evaluate.py — RAG Evaluation Harness with Citation Verification.

Runs the golden dataset through the full pipeline:
  Retrieve → Generate → Verify Citations → Score
"""

import json
import os
from time import perf_counter
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.retrieval.hybrid_search import HybridRetriever
from src.generation.generator import Generator
from src.generation.citation_verifier import verify_citations

console = Console()
DATASET_PATH = "data/golden_dataset/eval_set.json"


def evaluate():
    console.print(Panel.fit(
        "[bold cyan]RAG Evaluation Harness v2[/bold cyan]\n"
        "With citation verification + expanded 20-question golden dataset"
    ))

    if not os.path.exists(DATASET_PATH):
        console.print(f"[red]Dataset not found at {DATASET_PATH}[/red]")
        return

    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    retriever = HybridRetriever()
    generator = Generator()

    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        eval_task = progress.add_task(
            "[cyan]Evaluating queries...", total=len(dataset)
        )

        for item in dataset:
            start_time = perf_counter()
            query = item["question"]
            expected_mode = item["expected_mode"]
            expected_facts = item["expected_facts"]

            try:
                # 1. Retrieve
                context = retriever.retrieve(query, top_k=5)

                # 2. Generate
                answer = generator.generate_answer(query, context)

                # 3. Verify citations with retrieval confidence
                retrieval_conf = context[0].get("_retrieval_confidence", 0.0) if context else 0.0
                answer = verify_citations(answer, context, retrieval_confidence=retrieval_conf)

                # 4. Evaluate Mode
                actual_mode = answer.answer_mode
                mode_correct = actual_mode == expected_mode

                # 5. Evaluate Facts (only for non-Refuse questions)
                if expected_facts:
                    final_text_lower = answer.final_text.lower()
                    facts_found = [
                        fact.lower() in final_text_lower
                        for fact in expected_facts
                    ]
                    fact_recall = sum(facts_found) / len(expected_facts)
                else:
                    fact_recall = None  # Don't inflate average with freebies

                # 6. Citation verification rate
                total_cits = len(answer.citations) if answer.citations else 0
                verified_cits = 0
                if total_cits > 0:
                    verified_cits = sum(
                        1 for c in answer.citations
                        if "[UNVERIFIED" not in c.explanation
                    )
                cit_rate = (
                    verified_cits / total_cits if total_cits > 0 else None
                )

                latency = perf_counter() - start_time

                results.append({
                    "id": item["id"],
                    "query": query,
                    "mode_correct": mode_correct,
                    "expected_mode": expected_mode,
                    "actual_mode": actual_mode,
                    "fact_recall": fact_recall,
                    "citation_rate": cit_rate,
                    "confidence": answer.composite_confidence,
                    "latency": latency,
                })

            except Exception as e:
                console.print(f"[red]Error on {item['id']}: {e}[/red]")
                results.append({
                    "id": item["id"],
                    "query": query,
                    "mode_correct": False,
                    "expected_mode": expected_mode,
                    "actual_mode": "ERROR",
                    "fact_recall": 0.0,
                    "citation_rate": None,
                    "confidence": 0.0,
                    "latency": perf_counter() - start_time,
                })

            progress.advance(eval_task)

    # ──────────────────────────────────────────────────────────
    # Print Results Table
    # ──────────────────────────────────────────────────────────
    table = Table(title="Evaluation Results (20 Questions)")
    table.add_column("ID", style="cyan")
    table.add_column("Query", style="white", max_width=40)
    table.add_column("Routing", justify="center")
    table.add_column("Fact Recall", justify="center")
    table.add_column("Cit. Verified", justify="center")
    table.add_column("Confidence", justify="right")
    table.add_column("Latency", justify="right")

    total_routing = 0
    substantive_recall_sum = 0.0
    substantive_count = 0
    cit_verified_sum = 0.0
    cit_count = 0
    total_latency = 0.0

    for r in results:
        # Routing
        if r["mode_correct"]:
            routing_str = "[green]Pass[/green]"
            total_routing += 1
        else:
            routing_str = f"[red]Fail ({r['actual_mode']})[/red]"

        # Fact recall
        if r["fact_recall"] is not None:
            pct = r["fact_recall"] * 100
            recall_str = (
                f"[green]{pct:.0f}%[/green]"
                if pct >= 80
                else f"[yellow]{pct:.0f}%[/yellow]"
            )
            substantive_recall_sum += r["fact_recall"]
            substantive_count += 1
        else:
            recall_str = "[dim]N/A[/dim]"

        # Citation rate
        if r["citation_rate"] is not None:
            cpct = r["citation_rate"] * 100
            cit_str = (
                f"[green]{cpct:.0f}%[/green]"
                if cpct >= 80
                else f"[yellow]{cpct:.0f}%[/yellow]"
            )
            cit_verified_sum += r["citation_rate"]
            cit_count += 1
        else:
            cit_str = "[dim]N/A[/dim]"

        conf_str = (
            f"{r['confidence']:.2f}"
            if r["confidence"] is not None
            else "N/A"
        )

        table.add_row(
            r["id"],
            r["query"][:37] + "..." if len(r["query"]) > 37 else r["query"],
            routing_str,
            recall_str,
            cit_str,
            conf_str,
            f"{r['latency']:.1f}s",
        )

        total_latency += r["latency"]

    n = len(results)
    if n > 0:
        console.print(table)

        summary = Table.grid(padding=1)
        summary.add_row(
            "[bold]Routing Accuracy:[/bold]",
            f"[green]{(total_routing / n) * 100:.1f}%[/green] ({total_routing}/{n})",
        )
        if substantive_count > 0:
            summary.add_row(
                "[bold]Fact Recall (substantive only):[/bold]",
                f"{(substantive_recall_sum / substantive_count) * 100:.1f}% ({substantive_count} questions)",
            )
        if cit_count > 0:
            summary.add_row(
                "[bold]Citation Verification Rate:[/bold]",
                f"{(cit_verified_sum / cit_count) * 100:.1f}% ({cit_count} answers with citations)",
            )
        summary.add_row(
            "[bold]Average Latency:[/bold]",
            f"{total_latency / n:.1f}s",
        )

        console.print(Panel(summary, title="[bold]Metrics Summary[/bold]"))


if __name__ == "__main__":
    evaluate()
