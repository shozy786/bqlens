from __future__ import annotations

import logging

import click
from rich.console import Console

from . import __version__
from .catalog import Catalog
from .jobs import fetch, read_file
from .render import to_console
from .report import build

_existing_file = click.Path(exists=True, dir_okay=False)


@click.group()
@click.version_option(__version__)
def main() -> None:
    """Find where your BigQuery bytes go."""
    # sqlglot warns about every scripting statement it falls back on; that's noise here
    logging.getLogger("sqlglot").setLevel(logging.ERROR)


@main.command()
@click.argument("jobs_file", type=_existing_file)
@click.option("--catalog", "catalog_file", type=_existing_file, help="Table metadata as JSON.")
@click.option("--top", default=15, show_default=True, help="How many query groups to show.")
def analyze(jobs_file: str, catalog_file: str | None, top: int) -> None:
    """Analyze an exported job history (JSON or JSONL from INFORMATION_SCHEMA.JOBS)."""
    catalog = Catalog.from_json(catalog_file) if catalog_file else Catalog()
    report = build(read_file(jobs_file), catalog)
    to_console(report, Console(), top=top)


@main.command()
@click.option("--project", required=True, help="Project whose job history to read.")
@click.option("--region", default="us", show_default=True, help="Region qualifier, e.g. us, eu, europe-west3.")
@click.option("--days", default=30, show_default=True, help="How far back to look.")
@click.option("--top", default=15, show_default=True, help="How many query groups to show.")
def scan(project: str, region: str, days: int, top: int) -> None:
    """Analyze live job history straight from INFORMATION_SCHEMA."""
    try:
        from google.cloud import bigquery
    except ImportError:
        raise click.ClickException("scan needs the BigQuery client: pip install 'bqlens[bigquery]'") from None
    client = bigquery.Client(project=project)
    catalog = Catalog.from_bigquery(client, project, region)
    report = build(fetch(client, project, region, days), catalog)
    to_console(report, Console(), top=top)
