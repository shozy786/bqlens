"""Table metadata: how each table is partitioned and clustered, and how big it is."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CATALOG_SQL = """
SELECT
  CONCAT(c.table_catalog, '.', c.table_schema, '.', c.table_name) AS id,
  COUNT(*) AS num_columns,
  MAX(IF(c.is_partitioning_column = 'YES', c.column_name, NULL)) AS partition_column,
  ARRAY_AGG(IF(c.clustering_ordinal_position IS NULL, NULL, c.column_name)
            IGNORE NULLS ORDER BY c.clustering_ordinal_position) AS clustering,
  ANY_VALUE(s.total_logical_bytes) AS num_bytes
FROM `{project}`.`region-{region}`.INFORMATION_SCHEMA.COLUMNS AS c
LEFT JOIN `{project}`.`region-{region}`.INFORMATION_SCHEMA.TABLE_STORAGE AS s
  ON s.project_id = c.table_catalog
 AND s.table_schema = c.table_schema
 AND s.table_name = c.table_name
GROUP BY id
"""


@dataclass(frozen=True, slots=True)
class Table:
    id: str  # project.dataset.table
    partition_column: str | None = None
    clustering: tuple[str, ...] = ()
    num_bytes: int = 0
    num_columns: int | None = None

    @property
    def partitioned(self) -> bool:
        return self.partition_column is not None


class Catalog:
    def __init__(self, tables: Iterable[Table] = ()) -> None:
        self._tables = {t.id: t for t in tables}

    def get(self, table_id: str) -> Table | None:
        return self._tables.get(table_id)

    def __iter__(self) -> Iterator[Table]:
        return iter(self._tables.values())

    def __len__(self) -> int:
        return len(self._tables)

    @classmethod
    def from_json(cls, path: str | Path) -> Catalog:
        """Load a JSON list of objects with the same fields as :class:`Table`."""
        return cls(_table(row) for row in json.loads(Path(path).read_text()))

    @classmethod
    def from_bigquery(cls, client: Any, project: str, region: str) -> Catalog:
        """Read partitioning, clustering and sizes for every table in a project region."""
        rows = client.query(CATALOG_SQL.format(project=project, region=region.lower())).result()
        return cls(_table(dict(row.items())) for row in rows)


def _table(row: dict[str, Any]) -> Table:
    return Table(
        id=row["id"],
        partition_column=row.get("partition_column"),
        clustering=tuple(row.get("clustering") or ()),
        num_bytes=int(row.get("num_bytes") or 0),
        num_columns=row.get("num_columns"),
    )
