"""
cli.py — Command-line interface for the ingestion pipeline.

Commands:
    ingest    Ingest a single document into the knowledge base
    list      List all ingested documents
    status    Show status of a specific document by doc_id prefix
    health    Print system health summary

Usage:
    python -m src.ingestion.cli ingest <file> --regulator CBUAE --type federal_law \\
        --title "CBUAE Federal Decree-Law No. 6 of 2025" \\
        --url "https://uaelegislation.gov.ae/en/legislations/3284"

    python -m src.ingestion.cli list
    python -m src.ingestion.cli health
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from .metadata import DocType, LanguageAuthority, Regulator
from .pipeline import (
    get_system_health,
    ingest_document,
    list_ingested_documents,
)

console = Console()


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """UAE Regulatory Compliance RAG Agent — Ingestion CLI."""


# ---------------------------------------------------------------------------
# ingest command
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("file_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--regulator", "-r",
    required=True,
    type=click.Choice([r.value for r in Regulator], case_sensitive=False),
    help="Issuing regulatory body (CBUAE, VARA, CMA, DFSA, FSRA)",
)
@click.option(
    "--type", "-t", "doc_type",
    required=True,
    type=click.Choice([d.value for d in DocType], case_sensitive=False),
    help="Document type",
)
@click.option("--title", required=True, help="Official document title")
@click.option("--url", "source_url", required=True, help="Official public URL of the document")
@click.option(
    "--effective-date",
    default=None,
    type=click.DateTime(formats=["%Y-%m-%d"]),
    help="Effective date (YYYY-MM-DD)",
)
@click.option(
    "--language",
    default="en_translation",
    type=click.Choice([l.value for l in LanguageAuthority], case_sensitive=False),
    help="Language authority of the document",
)
@click.option(
    "--no-force", "not_in_force",
    is_flag=True,
    default=False,
    help="Mark document as no longer in force",
)
@click.option(
    "--supersedes",
    default=None,
    help="doc_id of the document this one supersedes",
)
def ingest(
    file_path: Path,
    regulator: str,
    doc_type: str,
    title: str,
    source_url: str,
    effective_date: Optional[object],
    language: str,
    not_in_force: bool,
    supersedes: Optional[str],
) -> None:
    """Ingest a regulatory document into the knowledge base."""

    eff_date: Optional[date] = None
    if effective_date is not None:
        eff_date = effective_date.date()  # type: ignore[attr-defined]

    console.print(f"\n[bold blue]>> Ingesting:[/bold blue] {file_path.name}")
    console.print(f"   Regulator : [cyan]{regulator}[/cyan]")
    console.print(f"   Type      : [cyan]{doc_type}[/cyan]")
    console.print(f"   Title     : {title}")
    console.print()

    result = ingest_document(
        file_path=file_path,
        title=title,
        regulator=Regulator(regulator),
        doc_type=DocType(doc_type),
        source_url=source_url,
        effective_date=eff_date,
        language_authority=LanguageAuthority(language),
        in_force=not not_in_force,
        supersedes=supersedes,
    )

    if result.success:
        console.print(f"[bold green]OK Ingestion successful[/bold green]")
        console.print(f"   doc_id      : [dim]{result.doc_id[:32]}…[/dim]")
        console.print(f"   Chunks      : [bold]{result.chunk_count}[/bold]")
        console.print(f"   Total tokens: {result.total_tokens:,}")
        console.print(f"   Pages       : {result.page_count}")
        console.print(f"   Output      : [dim]{result.output_path}[/dim]")
        if result.parse_warnings:
            console.print("\n[yellow]  Parse warnings:[/yellow]")
            for w in result.parse_warnings:
                console.print(f"   • {w}")
        if result.chunk_warnings:
            console.print("\n[yellow]  Chunk warnings:[/yellow]")
            for w in result.chunk_warnings:
                console.print(f"   • {w}")
    else:
        console.print(f"[bold red]FAIL Ingestion failed[/bold red]")
        console.print(f"   Error: {result.error}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------

@cli.command("list")
def list_docs() -> None:
    """List all ingested documents in the knowledge base."""
    docs = list_ingested_documents()

    if not docs:
        console.print("\n[yellow]No documents ingested yet.[/yellow]")
        console.print("Run: [bold]python -m src.ingestion.cli ingest <file> ...[/bold]\n")
        return

    table = Table(title=f"Knowledge Base -- {len(docs)} document(s)", show_lines=True)
    table.add_column("Doc ID (prefix)", style="dim", no_wrap=True)
    table.add_column("Title", style="bold")
    table.add_column("Regulator", style="cyan")
    table.add_column("Type")
    table.add_column("Chunks", justify="right")
    table.add_column("Tokens", justify="right")
    table.add_column("Pages", justify="right")
    table.add_column("Ingested At", style="dim")

    for doc in docs:
        if "error" in doc:
            table.add_row(doc.get("file", "?"), f"[red]ERROR: {doc['error']}[/red]", "", "", "", "", "", "")
        else:
            table.add_row(
                doc.get("doc_id", "?"),
                doc.get("title", "?"),
                doc.get("regulator", "?"),
                doc.get("doc_type", "?"),
                str(doc.get("total_chunks", 0)),
                f"{doc.get('total_tokens', 0):,}",
                str(doc.get("page_count", 0)),
                doc.get("ingested_at", "?")[:19],
            )

    console.print(table)


# ---------------------------------------------------------------------------
# status command
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("doc_id_prefix")
def status(doc_id_prefix: str) -> None:
    """Show detailed status of a document by its doc_id prefix."""
    docs = list_ingested_documents()
    matches = [d for d in docs if d.get("doc_id", "").startswith(doc_id_prefix)]

    if not matches:
        console.print(f"\n[red]No document found with doc_id prefix: {doc_id_prefix}[/red]")
        sys.exit(1)

    for doc in matches:
        rprint(doc)


# ---------------------------------------------------------------------------
# health command
# ---------------------------------------------------------------------------

@cli.command()
def health() -> None:
    """Print system health summary."""
    h = get_system_health()

    console.print("\n[bold blue]== System Health ==[/bold blue]")
    status_icon = "[OK]" if h["processed_dir_exists"] else "[!]"
    console.print(f"   {status_icon} Processed dir   : {h['processed_dir']}")
    status_icon = "[OK]" if h["logs_dir_exists"] else "[!]"
    console.print(f"   {status_icon} Logs dir         : {h['logs_dir']}")
    console.print(f"   Documents      : [bold]{h['document_count']}[/bold]")
    console.print(f"   Total chunks   : [bold]{h['total_chunks']}[/bold]")
    console.print(f"   Total tokens   : {h['total_tokens']:,}")
    console.print(f"   Last ingested  : {h['last_ingested_at']}")
    console.print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    cli()


if __name__ == "__main__":
    main()
