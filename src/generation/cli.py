"""
cli.py — CLI for Answer Generation.

Command:
    ask: Run a full end-to-end RAG query (Retrieve -> Generate -> Format).
"""

import logging
import click
from rich.console import Console

from src.retrieval.hybrid_search import HybridRetriever
from src.generation.generator import Generator
from src.generation.formatter import format_answer_markdown

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("generation")
logger.setLevel(logging.INFO)

console = Console()


@click.group()
def cli():
    """UAE Regulatory Compliance - Generation CLI."""
    pass


@cli.command()
@click.argument("query", type=str)
@click.option("--k", type=int, default=5, help="Number of chunks to retrieve for context")
@click.option("--regulator", type=str, default=None, help="Filter by Regulator (e.g. CBUAE, VARA)")
def ask(query: str, k: int, regulator: str):
    """Ask a compliance question and generate an AI answer."""
    console.print(f"\n[bold blue]>> Query:[/bold blue] {query}")
    
    filter_dict = None
    if regulator:
        filter_dict = {"regulator": regulator}
        console.print(f"   [dim]Filter: {filter_dict}[/dim]")

    # Step 1: Retrieval
    with console.status("[bold green]Step 1: Retrieving relevant regulatory chunks...[/bold green]"):
        try:
            retriever = HybridRetriever()
            retrieved_chunks = retriever.retrieve(query=query, top_k=k, filter_dict=filter_dict)
        except Exception as e:
            console.print(f"[bold red]Retrieval Error:[/bold red] {e}")
            return

    if not retrieved_chunks:
        console.print("[yellow]No relevant documents found. The AI cannot answer without context.[/yellow]")
        # We could still pass empty context to the Generator to let it 'Refuse', but short-circuiting saves API calls.
        return

    console.print(f"[dim]Retrieved top {len(retrieved_chunks)} chunks for context.[/dim]")

    # Step 2: Generation
    with console.status("[bold green]Step 2: Generating structured answer via Groq...[/bold green]"):
        try:
            generator = Generator()
            answer = generator.generate_answer(query, retrieved_chunks)
        except Exception as e:
            console.print(f"[bold red]Generation Error:[/bold red] {e}")
            return

    # Step 3: Formatting & Display
    md_text = format_answer_markdown(answer)
    
    # Print raw text safely to avoid Windows CP1252 Unicode errors
    console.print("\n[bold green]AI Compliance Agent[/bold green]\n")
    # Using python's built-in print with encoding fallback to be extremely safe on Windows
    print(md_text.encode("ascii", "replace").decode("ascii"))


if __name__ == "__main__":
    cli()
