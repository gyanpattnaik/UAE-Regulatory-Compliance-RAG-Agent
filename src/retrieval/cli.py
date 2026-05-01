"""
cli.py — CLI for managing the Retrieval Pipeline.

Commands:
    populate: Scan `data/processed/*.json`, embed/index all chunks, and save.
    query: Run a hybrid search query and print results.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.ingestion.pipeline import _PROCESSED_DIR
from src.retrieval.bm25_index import BM25Index
from src.retrieval.hybrid_search import HybridRetriever
from src.retrieval.vector_store import VectorStore

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("retrieval")
logger.setLevel(logging.INFO)

console = Console()


@click.group()
def cli():
    """UAE Regulatory Compliance - Retrieval Pipeline CLI."""
    pass


@cli.command()
@click.option("--processed-dir", type=click.Path(exists=True), default=str(_PROCESSED_DIR), help="Directory with processed JSON files")
def populate(processed_dir: str):
    """Populate Vector Store and BM25 index from processed documents."""
    console.print(f"\n[bold blue]>> Populating Knowledge Base from {processed_dir}[/bold blue]")
    
    p_dir = Path(processed_dir)
    json_files = list(p_dir.glob("*.json"))
    
    if not json_files:
        console.print("[yellow]No processed JSON files found.[/yellow]")
        return

    all_chunks: List[Dict[str, Any]] = []
    
    with console.status("[bold green]Loading JSON files...[/bold green]"):
        for jf in json_files:
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                chunks = data.get("chunks", [])
                all_chunks.extend(chunks)
                logger.info(f"Loaded {len(chunks)} chunks from {jf.name}")
            except Exception as e:
                logger.error(f"Failed to read {jf.name}: {e}")

    console.print(f"Total chunks loaded: [bold]{len(all_chunks)}[/bold]")

    # 1. Populate Vector Store
    with console.status("[bold green]Generating dense embeddings (this may take a moment)...[/bold green]"):
        vs = VectorStore()
        # Chroma upsert is idempotent based on chunk_id
        vs.add_chunks(all_chunks)
    console.print("[OK] Vector Store updated.")

    # 2. Populate BM25
    with console.status("[bold green]Building BM25 sparse index...[/bold green]"):
        bm25 = BM25Index()
        bm25.build_index(all_chunks)
        bm25.save()
    console.print("[OK] BM25 Index built and saved.")
    
    console.print("\n[bold green]Populate complete![/bold green] Ready for queries.\n")


@cli.command()
@click.argument("query_string", type=str)
@click.option("--k", type=int, default=5, help="Number of results to retrieve")
@click.option("--regulator", type=str, default=None, help="Filter by Regulator (e.g. CBUAE, VARA)")
def query(query_string: str, k: int, regulator: str):
    """Run a hybrid search query."""
    console.print(f"\n[bold blue]>> Query:[/bold blue] {query_string}")
    
    filter_dict = None
    if regulator:
        filter_dict = {"regulator": regulator}
        console.print(f"   [dim]Filter: {filter_dict}[/dim]")

    with console.status("[bold green]Retrieving and Reranking...[/bold green]"):
        retriever = HybridRetriever()
        results = retriever.retrieve(query=query_string, top_k=k, filter_dict=filter_dict)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    console.print(f"\n[bold]Top {len(results)} Results:[/bold]\n")

    for i, res in enumerate(results, 1):
        meta = res["metadata"]
        score = res.get("cross_encoder_score", 0.0)
        
        # Format the chunk text
        text_preview = res["text"].replace("\n", " ")
        if len(text_preview) > 200:
            text_preview = text_preview[:200] + "..."

        header = f"[cyan]{meta['regulator']}[/cyan] | {meta['doc_type']} | {meta.get('section_heading', 'N/A')} (Score: {score:.3f})"
        
        console.print(Panel(text_preview, title=f"#{i} {header}", title_align="left"))


if __name__ == "__main__":
    cli()
