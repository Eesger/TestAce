"""CLI entry point — xarchiver auth | sync | search | stats"""
from __future__ import annotations

import logging
import sys

import click
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


@click.group()
@click.option("--debug", is_flag=True, help="Enable debug logging.")
def main(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


@main.command()
def auth() -> None:
    """Run the OAuth 2.0 PKCE flow and save tokens to .env."""
    from .auth import run_auth_flow
    run_auth_flow()


@main.command()
@click.option("--full", is_flag=True, help="Re-sync all pages, ignoring stored cursor.")
def sync(full: bool) -> None:
    """Fetch new bookmarks, extract articles, and update embeddings."""
    from .sync import run_sync
    from . import db

    db.init_db()
    console.print("[bold cyan]Starting sync...[/]")
    result = run_sync(full=full)

    table = Table(box=box.SIMPLE)
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("New tweets", str(result.new_tweets))
    table.add_row("Articles extracted", str(result.new_articles))
    table.add_row("New embeddings", str(result.new_embeddings))
    if result.errors:
        table.add_row("[red]Errors[/]", str(len(result.errors)))
    console.print(table)

    if result.errors:
        for err in result.errors[:5]:
            console.print(f"  [red]•[/] {err}")


@main.command()
@click.argument("query")
@click.option(
    "--mode",
    type=click.Choice(["fts", "semantic", "hybrid"], case_sensitive=False),
    default="hybrid",
    show_default=True,
    help="Search mode.",
)
@click.option("--limit", default=10, show_default=True, help="Max results.")
def search(query: str, mode: str, limit: int) -> None:
    """Search the knowledge base. Modes: fts, semantic, hybrid (default)."""
    from .search import fts_search, semantic_search, hybrid_search
    from . import db

    db.init_db()

    fn = {"fts": fts_search, "semantic": semantic_search, "hybrid": hybrid_search}[mode.lower()]
    hits = fn(query, limit=limit)

    if not hits:
        console.print("[yellow]No results found.[/]")
        return

    console.print(f"\n[bold]Results for:[/] [cyan]{query}[/]  [dim]({mode}, {len(hits)} hits)[/]\n")
    for i, hit in enumerate(hits, 1):
        kind = "tweet" if hit.doc_id.startswith("tweet:") else "article"
        header = f"[bold]{i}.[/] [[{'blue' if kind == 'tweet' else 'green'}]{kind}[/]]"
        if hit.title:
            header += f"  [bold white]{hit.title}[/]"
        if hit.author:
            header += f"  [dim]@{hit.author}[/]"
        if hit.created_at:
            header += f"  [dim]{hit.created_at[:10]}[/]"
        console.print(header)
        if hit.snippet:
            snippet = hit.snippet.replace("\n", " ").strip()[:280]
            console.print(f"   {snippet}")
        if hit.url:
            console.print(f"   [link={hit.url}]{hit.url}[/link]")
        console.print(f"   [dim]score={hit.score:.4f}[/]\n")


@main.command()
def stats() -> None:
    """Show database statistics."""
    from . import db

    db.init_db()
    s = db.get_stats()

    table = Table(title="Knowledge Base Stats", box=box.ROUNDED)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Tweets stored", str(s["tweets"]))
    table.add_row("Articles (total URLs)", str(s["articles"]))
    table.add_row("Articles with text", str(s["articles_with_text"]))
    table.add_row("Embeddings", str(s["embeddings"]))
    table.add_row("Last sync", str(s["last_sync"]))
    table.add_row("DB size (MB)", str(s["db_size_mb"]))
    console.print(table)
