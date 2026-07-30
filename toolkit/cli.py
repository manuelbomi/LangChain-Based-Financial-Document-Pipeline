"""
`toolkit` command-line entrypoint (Typer app).

Architectural role
-------------------
The CLI is a thin presentation layer over ``toolkit.pipeline.run_pipeline``,
``toolkit.validation``, and ``toolkit.indexing`` -- it contains no business
logic of its own, only argument parsing, user-facing formatting, and exit
codes. That keeps every behavior here independently testable (and reusable)
without going through subprocess invocations of the CLI itself.

Commands
--------
- ``toolkit ingest --source <core-banking|relational-db|unstructured-files>``
- ``toolkit reindex [--source ...] [--since YYYY-MM-DD]``
- ``toolkit validate --source <...>``   (validate only, no indexing side effects)
- ``toolkit dead-letter list``
- ``toolkit health-check``              (offline substitute for /healthz+/readyz)
"""

from __future__ import annotations

from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from toolkit.config import get_settings
from toolkit.connectors import CONNECTOR_REGISTRY
from toolkit.logging_utils import configure_logging
from toolkit.pipeline import run_pipeline
from toolkit.validation import DataQualityValidator, DeadLetterStore

app = typer.Typer(
    name="toolkit",
    help="Enterprise Document Pipeline Toolkit -- ingest, validate, chunk, and delta-index documents for RAG.",
    no_args_is_help=True,
)
dead_letter_app = typer.Typer(help="Inspect documents that failed validation.")
app.add_typer(dead_letter_app, name="dead-letter")

console = Console()

_SOURCE_CHOICES = sorted(CONNECTOR_REGISTRY.keys())


def _init() -> None:
    """Shared setup for every command: configure logging from settings."""
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)


@app.callback()
def main() -> None:
    """Enterprise Document Pipeline Toolkit CLI."""
    _init()


def _print_summary(summary) -> None:
    table = Table(title=f"Pipeline run {summary.run_id} ({summary.source} / {summary.strategy})")
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("Documents seen", str(summary.docs_seen))
    table.add_row("Newly indexed", str(summary.docs_indexed))
    table.add_row("Reindexed (changed)", str(summary.docs_reindexed))
    table.add_row("Skipped (unchanged)", str(summary.docs_skipped_unchanged))
    table.add_row("Failed validation", str(summary.docs_failed_validation))
    table.add_row("PII-flagged", str(len(summary.pii_flagged_doc_ids)))
    table.add_row("Stale documents", str(len(summary.stale_doc_ids)))
    console.print(table)
    if summary.pii_flagged_doc_ids:
        console.print(f"[yellow]PII pattern flags surfaced on:[/yellow] {', '.join(summary.pii_flagged_doc_ids)}")
    if summary.stale_doc_ids:
        console.print(f"[red]Stale (past freshness SLA):[/red] {', '.join(summary.stale_doc_ids)}")


@app.command()
def ingest(
    source: str = typer.Option(..., "--source", help=f"One of: {', '.join(_SOURCE_CHOICES)}"),
    strategy: str = typer.Option(
        "recursive", "--strategy", help="Chunking strategy: recursive|token-aware|semantic"
    ),
) -> None:
    """Run the full ingest pipeline (connect -> validate -> chunk -> enrich -> index) for one source."""
    settings = get_settings()
    try:
        summary = run_pipeline(settings, source=source, strategy=strategy)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from exc
    _print_summary(summary)
    if summary.docs_failed_validation:
        # Non-zero, non-fatal exit code: CI/schedulers can treat "some
        # documents dead-lettered" as a warning without failing the whole
        # job outright -- see README "Production Deployment".
        raise typer.Exit(code=1)


@app.command()
def reindex(
    source: str | None = typer.Option(
        None, "--source", help=f"Limit to one source: {', '.join(_SOURCE_CHOICES)}. Default: all sources."
    ),
    since: str | None = typer.Option(
        None, "--since", help="Only reindex documents effective on/after YYYY-MM-DD."
    ),
    strategy: str = typer.Option(
        "recursive", "--strategy", help="Chunking strategy: recursive|token-aware|semantic"
    ),
) -> None:
    """Re-run the ingest pipeline, relying on delta indexing to skip unchanged documents."""
    settings = get_settings()
    since_date = date.fromisoformat(since) if since else None
    sources = [source] if source else _SOURCE_CHOICES
    for src in sources:
        try:
            summary = run_pipeline(settings, source=src, strategy=strategy, since=since_date)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=2) from exc
        _print_summary(summary)


@app.command()
def validate(
    source: str = typer.Option(..., "--source", help=f"One of: {', '.join(_SOURCE_CHOICES)}"),
) -> None:
    """Run connector + validation only (no chunking/indexing side effects). Reports dead-letter routing."""
    settings = get_settings()
    if source not in CONNECTOR_REGISTRY:
        console.print(f"[red]unknown source '{source}'; choices: {_SOURCE_CHOICES}[/red]")
        raise typer.Exit(code=2)

    settings.ensure_state_dir()
    connector = CONNECTOR_REGISTRY[source]()
    dead_letter = DeadLetterStore(settings.dead_letter_path())
    validator = DataQualityValidator(dead_letter, run_id="validate-only")

    raw_docs = connector.fetch_all()
    outcomes = [validator.validate(raw) for raw in raw_docs]
    passed = sum(1 for o in outcomes if not o.rejected)
    failed = sum(1 for o in outcomes if o.rejected)
    pii = [o.document.doc_id for o in outcomes if o.document and o.pii_flags]

    table = Table(title=f"Validation report ({source})")
    table.add_column("Metric")
    table.add_column("Count", justify="right")
    table.add_row("Documents checked", str(len(outcomes)))
    table.add_row("Passed", str(passed))
    table.add_row("Failed (dead-lettered)", str(failed))
    table.add_row("PII-flagged", str(len(pii)))
    console.print(table)
    if failed:
        raise typer.Exit(code=1)


@dead_letter_app.command("list")
def dead_letter_list() -> None:
    """List every document ever routed to the dead-letter store."""
    settings = get_settings()
    store = DeadLetterStore(settings.dead_letter_path())
    entries = store.list_entries()
    if not entries:
        console.print("[green]Dead-letter store is empty.[/green]")
        return
    table = Table(title="Dead-letter store")
    table.add_column("doc_id")
    table.add_column("source_system")
    table.add_column("reason")
    table.add_column("run_id")
    table.add_column("recorded_at")
    for entry in entries:
        table.add_row(
            entry["doc_id"], entry["source_system"], entry["reason"], entry["run_id"], entry["recorded_at"]
        )
    console.print(table)


@app.command("health-check")
def health_check() -> None:
    """Offline health/readiness check: verifies config loads and every connector can list documents.

    Stands in for HTTP /healthz (process is up) + /readyz (dependencies
    reachable) for this CLI-first toolkit -- see README "Production
    Deployment" for how this maps onto a Kubernetes livenessProbe/readinessProbe
    when the toolkit is run as a scheduled Job rather than a long-lived service.
    """
    settings = get_settings()
    settings.ensure_state_dir()
    all_ok = True
    table = Table(title="Health check")
    table.add_column("Check")
    table.add_column("Status")
    table.add_row("Settings loaded", "[green]OK[/green]")
    for name, connector_cls in CONNECTOR_REGISTRY.items():
        try:
            connector_cls().list_documents()
            table.add_row(f"Connector: {name}", "[green]OK[/green]")
        except Exception as exc:  # noqa: BLE001 -- health check must not crash on any connector failure
            table.add_row(f"Connector: {name}", f"[red]FAIL: {exc}[/red]")
            all_ok = False
    console.print(table)
    if not all_ok:
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
