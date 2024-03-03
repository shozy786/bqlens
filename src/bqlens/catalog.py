"""Table metadata: how each table is partitioned and clustered, and how big it is."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path


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
        rows = json.loads(Path(path).read_text())
        return cls(
            Table(
                id=row["id"],
                partition_column=row.get("partition_column"),
                clustering=tuple(row.get("clustering") or ()),
                num_bytes=int(row.get("num_bytes") or 0),
                num_columns=row.get("num_columns"),
            )
            for row in rows
        )
