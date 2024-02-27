"""Normalize SQL so repeated runs of the same query with different literals group together."""

from __future__ import annotations

import hashlib

import sqlglot
from sqlglot import exp

DIALECT = "bigquery"


def normalize(sql: str) -> str:
    """Canonical text for ``sql``: formatting and comments dropped, literals replaced with ``?``."""
    statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
    return ";\n".join(
        _strip_literals(s).sql(dialect=DIALECT, comments=False, normalize_functions="upper")
        for s in statements
    )


def _strip_literals(tree: exp.Expression) -> exp.Expression:
    def replace(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.In) and node.expressions:
            # dashboards generate IN lists of every length; they're all the same query
            node.set("expressions", [exp.Placeholder()])
            return node
        if isinstance(node, exp.Literal):
            return exp.Placeholder()
        return node

    return tree.copy().transform(replace)


def fingerprint(sql: str) -> str:
    return hashlib.sha1(normalize(sql).encode()).hexdigest()[:16]
