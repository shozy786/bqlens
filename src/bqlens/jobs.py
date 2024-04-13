"""Query job records, as exported from ``INFORMATION_SCHEMA.JOBS``."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

JOBS_SQL = """
SELECT job_id, creation_time, user_email, project_id, query, statement_type, cache_hit,
       total_bytes_processed, total_bytes_billed, parent_job_id
FROM `{project}`.`region-{region}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
WHERE creation_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days:d} DAY)
  AND job_type = 'QUERY'
  AND state = 'DONE'
  AND error_result IS NULL
"""


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    created: datetime
    user: str
    query: str
    bytes_billed: int
    bytes_processed: int = 0
    statement_type: str | None = None
    cache_hit: bool = False
    parent_job_id: str | None = None
    project: str | None = None

    @property
    def billable(self) -> bool:
        """Whether this job's bytes should be counted.

        Cache hits cost nothing, and a SCRIPT job reports the sum of its child jobs,
        which show up in the history on their own with the actual statement text.
        """
        return not self.cache_hit and self.statement_type != "SCRIPT"

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Job:
        """Build a job from a row using the column names of the JOBS views."""
        return cls(
            job_id=row["job_id"],
            created=_timestamp(row["creation_time"]),
            user=row.get("user_email") or "unknown",
            query=row.get("query") or "",
            bytes_billed=int(row.get("total_bytes_billed") or 0),
            bytes_processed=int(row.get("total_bytes_processed") or 0),
            statement_type=row.get("statement_type"),
            cache_hit=_bool(row.get("cache_hit")),
            parent_job_id=row.get("parent_job_id"),
            project=row.get("project_id"),
        )


def _timestamp(value: Any) -> datetime:
    # the bq CLI, EXPORT DATA and the Python client all render TIMESTAMP differently
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) or value.replace(".", "", 1).isdigit():
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    return _timestamp(datetime.fromisoformat(value.removesuffix(" UTC").removesuffix("Z")))


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() == "true"
    return bool(value)


def read_file(path: str | Path) -> Iterator[Job]:
    """Read jobs from a JSON array (``bq query --format=json``) or newline-delimited JSON."""
    path = Path(path)
    with path.open() as fh:
        head = fh.read(1)
        while head.isspace():
            head = fh.read(1)
        fh.seek(0)
        if head == "[":
            rows = json.load(fh)
        else:
            rows = (json.loads(line) for line in fh if line.strip())
        for row in rows:
            yield Job.from_row(row)


def fetch(client: Any, project: str, region: str, days: int = 30) -> Iterator[Job]:
    """Pull query jobs from ``INFORMATION_SCHEMA.JOBS_BY_PROJECT`` with a ``bigquery.Client``.

    Needs ``bigquery.resourceViewer`` (or ``bigquery.jobs.listAll``) on the project.
    """
    sql = JOBS_SQL.format(project=project, region=region.lower(), days=days)
    for row in client.query(sql).result():
        yield Job.from_row(dict(row.items()))
