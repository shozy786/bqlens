"""Checks that turn a query's shape plus table metadata into findings."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .catalog import Catalog
from .predicates import QueryShape


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    severity: str  # high | medium | low
    table: str | None
    message: str


Rule = Callable[[QueryShape, Catalog], Iterator[Finding]]
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


def check(shape: QueryShape, catalog: Catalog) -> list[Finding]:
    return [finding for r in RULES for finding in r(shape, catalog)]


@rule
def missing_partition_filter(shape: QueryShape, catalog: Catalog) -> Iterator[Finding]:
    for table_id in sorted(shape.tables):
        table = catalog.get(table_id)
        if table is None or not table.partitioned:
            continue
        if table.partition_column.lower() not in shape.filtered_columns(table_id):
            yield Finding(
                "missing-partition-filter",
                "high",
                table_id,
                f"no filter on partition column `{table.partition_column}`, every partition is scanned",
            )
