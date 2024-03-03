"""Work out which tables a query reads and which of their columns it filters on."""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from .fingerprint import DIALECT

_KINDS: dict[type[exp.Expression], str] = {
    exp.EQ: "eq",
    exp.In: "eq",
    exp.Is: "eq",
    exp.GT: "range",
    exp.GTE: "range",
    exp.LT: "range",
    exp.LTE: "range",
    exp.Between: "range",
    exp.Like: "like",
}


@dataclass(frozen=True, slots=True)
class ColumnUse:
    table: str
    column: str
    kind: str  # eq | range | like | other


@dataclass
class QueryShape:
    tables: set[str] = field(default_factory=set)
    filters: list[ColumnUse] = field(default_factory=list)

    def filtered_columns(self, table: str) -> set[str]:
        return {f.column.lower() for f in self.filters if f.table == table}


def analyze(sql: str, default_project: str | None = None) -> QueryShape:
    shape = QueryShape()
    for statement in sqlglot.parse(sql, read=DIALECT):
        if statement is None:
            continue
        for scope in traverse_scope(statement):
            _collect(scope, shape, default_project)
    return shape


def table_id(table: exp.Table, default_project: str | None = None) -> str:
    parts = (table.catalog or default_project, table.db, table.name)
    return ".".join(p for p in parts if p)


def _collect(scope: Scope, shape: QueryShape, default_project: str | None) -> None:
    for source in scope.sources.values():
        if isinstance(source, exp.Table):
            shape.tables.add(table_id(source, default_project))

    for column in scope.columns:
        clause = column.find_ancestor(exp.Where, exp.Join, exp.Select)
        if not isinstance(clause, (exp.Where, exp.Join)):
            continue
        source = _source_of(scope, column)
        if isinstance(source, exp.Table):
            shape.filters.append(ColumnUse(table_id(source, default_project), column.name, _kind(column)))


def _source_of(scope: Scope, column: exp.Column) -> exp.Expression | Scope | None:
    if column.table:
        return scope.sources.get(column.table)
    return next(iter(scope.sources.values()), None)


def _kind(column: exp.Column) -> str:
    node = column.parent
    while node is not None and not isinstance(node, (exp.Where, exp.Join, exp.Select)):
        if type(node) in _KINDS:
            return _KINDS[type(node)]
        node = node.parent
    return "other"
