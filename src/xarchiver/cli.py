"""CLI entry point — xarchiver auth | sync | search | stats | brain-sync"""
from __future__ import annotations

import json as json_lib
import logging
import sys

import click
from rich.console import Console
from rich.table import Table
from rich import box

from .config import get_settings

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
    table.add_row("Ideas extracted", str(result.new_ideas))
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


@main.command("inspect-birdclaw")
def inspect_birdclaw() -> None:
    """Show what Birdclaw data is available on this machine (diagnostic)."""
    from .birdclaw_reader import print_schema_report
    from .config import get_settings
    print_schema_report(get_settings().birdclaw_home or None)


@main.command("notion-sync")
@click.option("--json", "as_json", is_flag=True, help="Output unpublished ideas as JSON.")
@click.option("--set-page-id", nargs=2, multiple=True, metavar="TWEET_ID PAGE_ID",
              help="Store a Notion page ID for a tweet (used by /sync-brain after MCP push).")
@click.option("--min-relevance", default=0.3, show_default=True,
              help="Minimum relevance score to include.")
def notion_sync(as_json: bool, set_page_id: tuple, min_relevance: float) -> None:
    """Manage Notion publishing state. Outputs pending ideas or records page IDs."""
    from . import db

    db.init_db()

    if set_page_id:
        for tweet_id, page_id in set_page_id:
            db.set_notion_page_id(tweet_id, page_id)
        if not as_json:
            console.print(f"[green]Stored {len(set_page_id)} Notion page ID(s).[/]")
        return

    rows = db.get_unpublished_ideas(min_relevance=min_relevance)

    if as_json:
        output = [
            {
                "tweet_id": r["tweet_id"],
                "author": r["author"],
                "summary": r["summary"],
                "key_concepts": json_lib.loads(r["key_concepts"] or "[]"),
                "category": r["category"],
                "tags": json_lib.loads(r["tags"] or "[]"),
                "relevance_score": r["relevance_score"],
                "tweet_text": r["tweet_text"],
                "article_title": r["article_title"],
                "article_url": r["article_url"],
                "article_body": (r["article_body"] or "")[:3000],
                "tweet_url": f"https://twitter.com/{r['author']}/status/{r['tweet_id']}",
                "bookmarked_at": r["tweet_created_at"],
            }
            for r in rows
        ]
        click.echo(json_lib.dumps(output, ensure_ascii=False, indent=2))
        return

    if not rows:
        console.print("[green]All ideas are in Notion.[/]")
        return

    console.print(f"\n[bold]{len(rows)} idea(s) not yet in Notion[/] [dim](≥{min_relevance} relevance)[/]\n")
    for r in rows:
        concepts = ", ".join(json_lib.loads(r["key_concepts"] or "[]"))
        console.print(f"[[cyan]{r['category']}[/]] @{r['author']}  "
                      f"[dim]score={r['relevance_score']:.2f}[/]")
        console.print(f"  {r['summary'][:120]}")
        if concepts:
            console.print(f"  [dim]{concepts}[/]")
        console.print()

    console.print("[dim]Run /sync-brain in Claude Code, or `xarchiver sync` with NOTION_API_TOKEN set.[/]")


@main.command()
@click.argument("tweet_id")
@click.option("--refetch-article", is_flag=True,
              help="Re-download and re-extract the article before reprocessing.")
@click.option("--push/--no-push", default=True, show_default=True,
              help="Update the Notion page after re-extraction.")
def reprocess(tweet_id: str, refetch_article: bool, push: bool) -> None:
    """Re-run Claude idea extraction for a specific bookmark. Updates Notion in place."""
    from . import db
    from .ideas import extract_idea
    from .extractor import extract_article as _extract_article

    db.init_db()

    tweet = db.get_tweet_by_id(tweet_id)
    if not tweet:
        console.print(f"[red]Tweet {tweet_id} not found in database.[/]")
        raise SystemExit(1)

    existing_idea = db.get_idea_by_tweet(tweet_id)
    existing_page_id = existing_idea["notion_page_id"] if existing_idea else None

    if refetch_article:
        console.print("[cyan]Re-fetching article...[/]")
        articles = db.get_conn().execute(
            "SELECT tweet_id, url FROM articles WHERE tweet_id=?", (tweet_id,)
        ).fetchall()
        for art_row in articles:
            art = _extract_article(art_row["tweet_id"], art_row["url"])
            db.upsert_article(art)

    article = db.get_best_article_for_tweet(tweet_id)
    console.print(f"[cyan]Re-extracting idea for tweet {tweet_id}...[/]")

    idea = extract_idea(
        tweet_id=tweet_id,
        tweet_text=tweet["text"],
        author=tweet["author_username"],
        article_id=article["id"] if article else None,
        article_title=article["title"] if article else None,
        article_body=article["body_text"] if article else None,
    )
    if not idea:
        console.print("[yellow]Extraction returned no result (tweet may be too short).[/]")
        return

    db.clear_idea(tweet_id)
    db.upsert_idea(db.IdeaData(
        tweet_id=idea.tweet_id, article_id=idea.article_id,
        summary=idea.summary, key_concepts=idea.key_concepts,
        category=idea.category, tags=idea.tags,
        relevance_score=idea.relevance_score,
    ))

    console.print(f"[green]Re-extracted:[/] [{idea.category}] {idea.summary[:120]}")

    if push:
        cfg = get_settings()
        if cfg.notion_api_token and cfg.notion_database_id:
            from .notion_publisher import publish_idea
            import json as _json
            page_id = publish_idea(
                tweet_id=tweet_id,
                author=tweet["author_username"],
                summary=idea.summary,
                key_concepts=idea.key_concepts,
                category=idea.category,
                tags=idea.tags,
                relevance=idea.relevance_score,
                tweet_text=tweet["text"],
                tweet_url=f"https://twitter.com/{tweet['author_username']}/status/{tweet_id}",
                article_title=article["title"] if article else None,
                article_body=article["body_text"] if article else None,
                article_url=article["url"] if article else None,
                existing_page_id=existing_page_id,
                is_reeval=existing_page_id is not None,
            )
            db.set_notion_page_id(tweet_id, page_id)
            action = "Updated" if existing_page_id else "Created"
            console.print(f"[green]{action} Notion page {page_id}[/]")
        else:
            console.print("[yellow]NOTION_API_TOKEN not set — skipping Notion update.[/]")


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
    table.add_row("Ideas extracted", str(s["ideas"]))
    table.add_row("Ideas in Notion", str(s["ideas_in_notion"]))
    table.add_row("Ideas pending Notion", str(s["ideas_pending_notion"]))
    table.add_row("Embeddings", str(s["embeddings"]))
    table.add_row("Last sync", str(s["last_sync"]))
    table.add_row("DB size (MB)", str(s["db_size_mb"]))
    console.print(table)
