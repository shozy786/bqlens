from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import click
from rich.console import Console

from . import __version__
from .catalog import Catalog
from .jobs import fetch, read_file
from .render import to_console, to_dict, to_markdown
from .report import Report, build

_existing_file = click.Path(exists=True, dir_okay=False)


def _output_options(fn: Callable[..., Any]) -> Callable[..., Any]:
    fn = click.option("--top", default=15, show_default=True, help="How many query groups to show.")(fn)
    fn = click.option(
        "--format", "fmt", type=click.Choice(["table", "json", "markdown"]), default="table", show_default=True
    )(fn)
    return fn


def _emit(report: Report, fmt: str, top: int) -> None:
    if fmt == "json":
        click.echo(json.dumps(to_dict(report, top), indent=2))
    elif fmt == "markdown":
        click.echo(to_markdown(report, top), nl=False)
    else:
        to_console(report, Console(), top=top)


@click.group()
@click.version_option(__version__)
def main() -> None:
    """Find where your BigQuery bytes go."""
    # sqlglot warns about every scripting statement it falls back on; that's noise here
    logging.getLogger("sqlglot").setLevel(logging.ERROR)


@main.command()
@click.argument("jobs_file", type=_existing_file)
@click.option("--catalog", "catalog_file", type=_existing_file, help="Table metadata as JSON.")
@_output_options
def analyze(jobs_file: str, catalog_file: str | None, fmt: str, top: int) -> None:
    """Analyze an exported job history (JSON or JSONL from INFORMATION_SCHEMA.JOBS)."""
    catalog = Catalog.from_json(catalog_file) if catalog_file else Catalog()
    _emit(build(read_file(jobs_file), catalog), fmt, top)


@main.command()
@click.option("--project", required=True, help="Project whose job history to read.")
@click.option("--region", default="us", show_default=True, help="Region qualifier, e.g. us, eu, europe-west3.")
@click.option("--days", default=30, show_default=True, help="How far back to look.")
@_output_options
def scan(project: str, region: str, days: int, fmt: str, top: int) -> None:
    """Analyze live job history straight from INFORMATION_SCHEMA."""
    try:
        from google.cloud import bigquery
    except ImportError:
        raise click.ClickException("scan needs the BigQuery client: pip install 'bqlens[bigquery]'") from None
    client = bigquery.Client(project=project)
    catalog = Catalog.from_bigquery(client, project, region)
    _emit(build(fetch(client, project, region, days), catalog), fmt, top)
