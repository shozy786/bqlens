from __future__ import annotations

import logging

import click
from rich.console import Console

from . import __version__
from .catalog import Catalog
from .jobs import read_file
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
