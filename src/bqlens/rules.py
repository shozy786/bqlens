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


# truncating to the partition granularity keeps pruning intact; most other functions don't
_PRUNE_SAFE = {"DATE", "DATE_TRUNC", "TIMESTAMP_TRUNC", "DATETIME_TRUNC"}
# ingestion-time partitioned tables can be pruned through either pseudo-column
_INGESTION_TIME = {"_partitiontime", "_partitiondate"}


@rule
def partition_filter(shape: QueryShape, catalog: Catalog) -> Iterator[Finding]:
    for table_id in sorted(shape.tables):
        table = catalog.get(table_id)
        if table is None or not table.partitioned:
            continue
        column = table.partition_column
        names = _INGESTION_TIME if column.lower() in _INGESTION_TIME else {column.lower()}
        uses = [f for f in shape.filters if f.table == table_id and f.column.lower() in names]
        if not uses:
            yield Finding(
                "missing-partition-filter",
                "high",
                table_id,
                f"no filter on partition column `{column}`, every partition is scanned",
            )
        elif all(u.wrapped and u.wrapped not in _PRUNE_SAFE for u in uses):
            yield Finding(
                "wrapped-partition-filter",
                "medium",
                table_id,
                f"partition column `{column}` is only filtered through {uses[0].wrapped}(), which can stop "
                f"BigQuery from pruning partitions; compare the bare column against a constant instead",
            )


@rule
def unbounded_wildcard(shape: QueryShape, catalog: Catalog) -> Iterator[Finding]:
    for table_id in sorted(t for t in shape.tables if t.endswith("*")):
        if "_table_suffix" in shape.filtered_columns(table_id):
            continue
        shards = catalog.matching(table_id)
        what = f"all {len(shards)} tables" if shards else "every table"
        yield Finding(
            "unbounded-wildcard",
            "high",
            table_id,
            f"wildcard query reads {what} matching `{table_id.rsplit('.', 1)[-1]}`; "
            "filter on _TABLE_SUFFIX to read only the shards you need",
        )


@rule
def select_star(shape: QueryShape, catalog: Catalog) -> Iterator[Finding]:
    for table_id in sorted(shape.star_tables):
        table = catalog.get(table_id)
        columns = table.num_columns if table else None
        if columns is not None and columns <= 8:
            continue  # narrow table, listing columns saves next to nothing
        what = f"all {columns} columns" if columns else "every column"
        yield Finding(
            "select-star",
            "medium",
            table_id,
            f"SELECT * reads {what}; storage is columnar and billed per column read, select only what you use",
        )


@rule
def limit_without_filter(shape: QueryShape, catalog: Catalog) -> Iterator[Finding]:
    if not shape.has_limit or shape.filters or shape.aggregates:
        return
    for table_id in sorted(shape.tables):
        table = catalog.get(table_id)
        if table is not None and table.clustering:
            continue  # on clustered tables BigQuery can stop reading blocks once the limit is met
        yield Finding(
            "limit-without-filter",
            "medium",
            table_id,
            "LIMIT does not reduce bytes billed, the whole table is still read; "
            "use the table preview or TABLESAMPLE SYSTEM to peek at data",
        )
