from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from . import __version__
from .catalog import Catalog
from .jobs import fetch, read_file
from .predicates import analyze as analyze_sql
from .render import to_console, to_dict, to_markdown
from .report import ON_DEMAND_USD_PER_TIB, Report, build
from .rules import check

_existing_file = click.Path(exists=True, dir_okay=False)
_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "never": 99}


def _report_options(fn: Callable[..., Any]) -> Callable[..., Any]:
    fn = click.option(
        "--usd-per-tib",
        type=float,
        default=ON_DEMAND_USD_PER_TIB,
        show_default=True,
        envvar="BQLENS_USD_PER_TIB",
        help="Price per TiB billed. On-demand rates differ by region; on editions use your effective rate.",
    )(fn)
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
@_report_options
def analyze(jobs_file: str, catalog_file: str | None, fmt: str, top: int, usd_per_tib: float) -> None:
    """Analyze an exported job history (JSON or JSONL from INFORMATION_SCHEMA.JOBS)."""
    catalog = Catalog.from_json(catalog_file) if catalog_file else Catalog()
    _emit(build(read_file(jobs_file), catalog, usd_per_tib), fmt, top)


@main.command()
@click.option("--project", required=True, help="Project whose job history to read.")
@click.option("--region", default="us", show_default=True, help="Region qualifier, e.g. us, eu, europe-west3.")
@click.option("--days", default=30, show_default=True, help="How far back to look.")
@_report_options
def scan(project: str, region: str, days: int, fmt: str, top: int, usd_per_tib: float) -> None:
    """Analyze live job history straight from INFORMATION_SCHEMA."""
    try:
        from google.cloud import bigquery
    except ImportError:
        raise click.ClickException("scan needs the BigQuery client: pip install 'bqlens[bigquery]'") from None
    client = bigquery.Client(project=project)
    catalog = Catalog.from_bigquery(client, project, region)
    _emit(build(fetch(client, project, region, days), catalog, usd_per_tib), fmt, top)


@main.command()
@click.argument("files", nargs=-1, type=_existing_file)
@click.option("--catalog", "catalog_file", type=_existing_file, help="Table metadata as JSON.")
@click.option("--project", help="Project that dataset.table references belong to.")
@click.option(
    "--fail-on",
    type=click.Choice(["low", "medium", "high", "never"]),
    default="high",
    show_default=True,
    help="Exit non-zero when a finding at this severity or above is found.",
)
def lint(files: tuple[str, ...], catalog_file: str | None, project: str | None, fail_on: str) -> None:
    """Check SQL files (or stdin) before they ever run.

    Point it at compiled dbt models in CI: bqlens lint target/compiled/**/*.sql
    """
    catalog = Catalog.from_json(catalog_file) if catalog_file else Catalog()
    sources = [(f, Path(f).read_text()) for f in files] or [("<stdin>", click.get_text_stream("stdin").read())]
    worst = 0
    for name, sql in sources:
        for f in check(analyze_sql(sql, project), catalog):
            worst = max(worst, _SEVERITY_RANK[f.severity])
            click.echo(f"{name}: {f.severity} {f.rule} {f.table or ''}: {f.message}")
    if worst >= _SEVERITY_RANK[fail_on]:
        raise SystemExit(1)
