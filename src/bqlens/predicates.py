"""Work out which tables a query reads and which of their columns it filters on."""

from __future__ import annotations

from collections.abc import Iterator
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
    star_tables: set[str] = field(default_factory=set)  # every column ends up in the output
    has_limit: bool = False
    aggregates: bool = False

    def filtered_columns(self, table: str) -> set[str]:
        return {f.column.lower() for f in self.filters if f.table == table}


def analyze(sql: str, default_project: str | None = None) -> QueryShape:
    shape = QueryShape()
    for statement in sqlglot.parse(sql, read=DIALECT):
        if statement is None:
            continue
        scopes = traverse_scope(statement)
        for scope in scopes:
            _collect(scope, shape, default_project)
        if scopes:
            # BigQuery prunes columns nobody consumes, so `SELECT *` inside a CTE is free unless
            # the star survives all the way to the outermost query
            shape.star_tables |= {table_id(t, default_project) for t in _star_sources(scopes[-1])}
            root = scopes[-1].expression
            shape.has_limit |= root.args.get("limit") is not None
            shape.aggregates |= root.args.get("group") is not None or root.find(exp.AggFunc) is not None
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
        resolved = _resolve(scope, column)
        if resolved is not None:
            table, name = resolved
            shape.filters.append(ColumnUse(table_id(table, default_project), name, _kind(column)))


def _resolve(scope: Scope, column: exp.Column, depth: int = 0) -> tuple[exp.Table, str] | None:
    """Follow ``column`` through CTEs and derived tables back to the base table it comes from.

    BigQuery pushes filters on pass-through columns down into the CTE, so a partition filter
    applied outside ``WITH x AS (SELECT * FROM t)`` still prunes ``t``.
    """
    source = _source_of(scope, column)
    if isinstance(source, exp.Table):
        return source, column.name
    if isinstance(source, Scope) and depth < 16:
        inner = _projection(source, column.name)
        if inner is not None:
            return _resolve(source, inner, depth + 1)
    return None


def _projection(scope: Scope, name: str) -> exp.Column | None:
    """The column that output ``name`` of a derived table passes through unchanged, if any."""
    select = scope.expression
    if not isinstance(select, exp.Select):
        return None
    star = None
    for projection in select.selects:
        if isinstance(projection, exp.Star) or isinstance(projection.this, exp.Star):
            star = projection
        elif projection.alias_or_name.lower() == name.lower():
            inner = projection.unalias()
            return inner if isinstance(inner, exp.Column) else None
    if star is not None:
        return exp.column(name, table=star.text("table") or None)
    return None


def _star_sources(scope: Scope) -> Iterator[exp.Table]:
    # renamed from union_scopes in newer sqlglot releases
    branches = getattr(scope, "set_operation_scopes", None) or getattr(scope, "union_scopes", None)
    if branches:
        for branch in branches:
            yield from _star_sources(branch)
        return
    if not isinstance(scope.expression, exp.Select):
        return
    for projection in scope.expression.selects:
        if isinstance(projection, exp.Star):
            star, sources = projection, [s for _, s in scope.selected_sources.values()]
        elif isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
            star, sources = projection.this, [scope.sources.get(projection.table)]
        else:
            continue
        if star.args.get("except") or star.args.get("except_"):
            continue
        for source in sources:
            if isinstance(source, exp.Table):
                yield source
            elif isinstance(source, Scope):
                yield from _star_sources(source)


def _source_of(scope: Scope, column: exp.Column) -> exp.Expression | Scope | None:
    if column.table:
        return scope.sources.get(column.table)
    # scope.sources also lists every CTE in the WITH clause; only FROM/JOIN sources count here
    selected = list(scope.selected_sources.values())
    return selected[0][1] if selected else None


def _kind(column: exp.Column) -> str:
    node = column.parent
    while node is not None and not isinstance(node, (exp.Where, exp.Join, exp.Select)):
        if type(node) in _KINDS:
            return _KINDS[type(node)]
        node = node.parent
    return "other"
