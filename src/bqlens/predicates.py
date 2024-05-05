"""Work out which tables a query reads and which of their columns it filters on."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
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
    wrapped: str | None = None  # outermost function applied to the column, e.g. "FORMAT_DATE"


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
    try:
        statements = sqlglot.parse(sql, read=DIALECT)
    except SqlglotError:
        return shape  # nothing to say about a query we can't read; it still shows up by cost
    for statement in statements:
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
        if not _in_filter(column):
            continue
        resolved = _resolve(scope, column)
        if resolved is not None:
            table, name = resolved
            shape.filters.append(ColumnUse(table_id(table, default_project), name, *_classify(column)))


def _in_filter(column: exp.Column) -> bool:
    clause = column.find_ancestor(exp.Where, exp.Join, exp.Select)
    if isinstance(clause, exp.Where):
        return True
    if isinstance(clause, exp.Join):
        # JOIN ... ON counts, the joined expression itself (e.g. UNNEST(items)) does not
        node = column
        while node.parent is not clause:
            node = node.parent
        return node.arg_key == "on"
    return False


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
    selected = scope.selected_sources
    if column.name in selected and isinstance(selected[column.name][0], exp.Unnest):
        return None  # UNNEST(tags) AS tag ... WHERE tag = 'x'
    # UNNEST'd structs are almost always referenced qualified, so they don't make a column
    # ambiguous. Two real sources do, and without a schema guessing would misattribute it.
    candidates = [source for node, source in selected.values() if not isinstance(node, exp.Unnest)]
    return candidates[0] if len(candidates) == 1 else None


def _classify(column: exp.Column) -> tuple[str, str | None]:
    """How ``column`` is compared, and the function wrapped around it on the way, if any."""
    wrapped = None
    child, node = column, column.parent
    while node is not None and not isinstance(node, (exp.Where, exp.Join, exp.Select)):
        kind = _KINDS.get(type(node))
        if kind is not None:
            # column-to-column comparisons (join keys, script variables, IN subqueries)
            # are only known at run time and can't prune blocks
            others = (e for e in node.iter_expressions() if e is not child)
            return ("other" if any(e.find(exp.Column) for e in others) else kind), wrapped
        if isinstance(node, exp.Func):
            # name it the way the user wrote it; sqlglot's class names are dialect-neutral
            wrapped = node.sql(dialect=DIALECT).split("(", 1)[0].upper()
        child, node = node, node.parent
    return "other", wrapped
