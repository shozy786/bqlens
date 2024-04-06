"""Suggest clustering columns from how tables are actually filtered."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .catalog import Catalog
from .predicates import QueryShape

# block pruning works best on equality, decently on ranges, and on LIKE only for prefixes
_WEIGHT = {"eq": 1.0, "range": 0.6, "like": 0.3}
MAX_COLUMNS = 4  # BigQuery's limit
MIN_TABLE_BYTES = 1024**3  # below ~1 GiB clustering barely moves bytes billed


@dataclass(frozen=True, slots=True)
class ClusteringAdvice:
    table: str
    current: tuple[str, ...]
    suggested: tuple[str, ...]
    bytes_affected: int  # billed bytes of queries that filter on a suggested column
    bytes_total: int  # billed bytes of all queries reading the table

    @property
    def coverage(self) -> float:
        return self.bytes_affected / self.bytes_total if self.bytes_total else 0.0


def recommend(usage: Iterable[tuple[QueryShape, int]], catalog: Catalog) -> list[ClusteringAdvice]:
    """Rank filter columns per table, weighted by the bytes the filtering queries were billed.

    ``usage`` pairs each distinct query shape with the bytes billed across all of its runs.
    A query's bytes are split across the tables it reads in proportion to their size, so a
    small dimension table joined to a huge fact table doesn't get credit for the fact scan.
    """
    scores: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    table_bytes: dict[str, int] = defaultdict(int)
    filtered: dict[str, list[tuple[float, set[str]]]] = defaultdict(list)

    for shape, billed in usage:
        known = {t: catalog.get(t) for t in shape.tables}
        known = {t: meta for t, meta in known.items() if meta is not None}
        total_size = sum(meta.num_bytes for meta in known.values())
        for table_id, meta in known.items():
            share = billed * meta.num_bytes / total_size if total_size else billed / len(known)
            table_bytes[table_id] += int(share)
            best: dict[str, float] = {}
            for use in shape.filters:
                if use.table != table_id or use.column.lower() == (meta.partition_column or "").lower():
                    continue
                weight = _WEIGHT.get(use.kind, 0.0)
                best[use.column.lower()] = max(best.get(use.column.lower(), 0.0), weight)
            for column, weight in best.items():
                scores[table_id][column] += share * weight
            filtered[table_id].append((share, {c for c, w in best.items() if w}))

    advice = []
    for table_id, by_column in scores.items():
        meta = catalog.get(table_id)
        if meta.num_bytes and meta.num_bytes < MIN_TABLE_BYTES:
            continue
        ranked = [c for c in sorted(by_column, key=by_column.get, reverse=True) if by_column[c]][:MAX_COLUMNS]
        if not ranked:
            continue
        current = tuple(c.lower() for c in meta.clustering)
        if current and ranked[0] in current:
            continue  # the most useful column is already clustered; reordering isn't worth a rewrite
        advice.append(
            ClusteringAdvice(
                table=table_id,
                current=meta.clustering,
                suggested=tuple(ranked),
                bytes_affected=int(sum(share for share, cols in filtered[table_id] if cols & set(ranked))),
                bytes_total=table_bytes[table_id],
            )
        )
    return sorted(advice, key=lambda a: a.bytes_affected, reverse=True)
