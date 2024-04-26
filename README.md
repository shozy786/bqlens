# bqlens

Find out where your BigQuery bytes go, and what to change so they stop going there.

bqlens reads your query job history, groups runs of the same query together (a dashboard
tile that ran 4,000 times last month is one line, not 4,000), ranks them by bytes billed and
checks each one against how the tables it reads are partitioned and clustered.

```
$ bqlens scan --project acme-analytics --region us --days 30

9 jobs, 5.74 TiB billed, about $35.84 at $6.25/TiB

┏━━━┳━━━━━━━━┳━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ # ┃   cost ┃ runs ┃    per run ┃ users ┃ query                                                   ┃
┡━━━╇━━━━━━━━╇━━━━━━╇━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 1 │ $30.01 │    2 │   2.40 TiB │     1 │ SELECT * FROM `acme-analytics.web.events` WHERE user_id │
│   │        │      │            │       │ = ? ●                                                   │
│ 2 │  $4.88 │    1 │ 800.00 GiB │     1 │ SELECT event_name, COUNT(*) FROM                        │
│   │        │      │            │       │ `acme-analytics.ga4.events_*` GROUP BY ? ●              │
│ 3 │  $0.73 │    3 │  39.83 GiB │     1 │ SELECT country, COUNT(*) AS n FROM                      │
│   │        │      │            │       │ `acme-analytics.web.events` WHERE event_date…           │
└───┴────────┴──────┴────────────┴───────┴─────────────────────────────────────────────────────────┘

Findings

#1 286674affd2484f6 · sample job bquxjob_05
  missing-partition-filter acme-analytics.web.events: no filter on partition column `event_date`, 
every partition is scanned
  select-star acme-analytics.web.events: SELECT * reads all 48 columns; storage is columnar and 
billed per column read, select only what you use

#2 21df88d3696c3cde · sample job bquxjob_07
  unbounded-wildcard acme-analytics.ga4.events_*: wildcard query reads all 3 tables matching 
`events_*`; filter on _TABLE_SUFFIX to read only the shards you need

Clustering

  acme-analytics.web.events (currently: none)
  CLUSTER BY user_id, event_name would help 100% of the 4.92 TiB read from it
```

## Install

```bash
pip install bqlens               # analyze exported job history, lint SQL files
pip install 'bqlens[bigquery]'   # also read straight from INFORMATION_SCHEMA
```

Python 3.10+.

## Usage

### Live, from INFORMATION_SCHEMA

```bash
bqlens scan --project acme-analytics --region eu --days 30
```

Uses Application Default Credentials. You need `bigquery.jobs.listAll` on the project (part of
`roles/bigquery.resourceViewer`) to see everyone's jobs, plus metadata access to the datasets
whose tables you want partitioning and clustering checked against.

### From an export

If you'd rather not grant access to the tool, export the history once and analyze it offline:

```bash
bq query --format=json --max_rows=1000000 --nouse_legacy_sql '
  SELECT job_id, creation_time, user_email, project_id, query, statement_type, cache_hit,
         total_bytes_processed, total_bytes_billed, parent_job_id
  FROM `region-us`.INFORMATION_SCHEMA.JOBS_BY_PROJECT
  WHERE creation_time > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    AND job_type = "QUERY" AND state = "DONE" AND error_result IS NULL' > jobs.json

bqlens analyze jobs.json --catalog tables.json
```

`tables.json` describes the tables to check against; without it bqlens still groups and ranks
queries but can only flag `SELECT *` and wildcard scans:

```json
[
  {"id": "acme-analytics.web.events", "partition_column": "event_date", "clustering": ["user_id"],
   "num_bytes": 2638827906662, "num_columns": 48}
]
```

### Lint SQL before it runs

```bash
bqlens lint --catalog tables.json --project acme-analytics target/compiled/**/*.sql
```

Exits 1 when it finds anything at `--fail-on` severity or above (default `high`), so it can
gate compiled dbt models in CI. Reads stdin when no files are given.

### Output

`--format table` (default), `json`, or `markdown` for pasting into a ticket. `--top N` limits
how many query groups are shown. `--usd-per-tib` (or `BQLENS_USD_PER_TIB`) sets the price used
for cost figures; the default is the US on-demand rate.

## What it checks

| rule | severity | |
|---|---|---|
| `missing-partition-filter` | high | Partitioned table read with no predicate on the partition column |
| `wrapped-partition-filter` | medium | Partition column only filtered through a function like `FORMAT_DATE()` or `CAST()`, which can stop pruning |
| `unbounded-wildcard` | high | `dataset.events_*` read without a `_TABLE_SUFFIX` filter |
| `select-star` | medium | `SELECT *` on a wide table that survives to the final output (a `*` inside a CTE is free if the outer query picks columns) |
| `limit-without-filter` | medium | `LIMIT` used to make a query cheap on an unclustered table; it doesn't |

Filters are traced through CTEs and subqueries the way BigQuery pushes them down, so
`WITH e AS (SELECT * FROM events) SELECT ... FROM e WHERE event_date = ...` counts as a partition
filter on `events`.

**Clustering suggestions** rank every column each table is filtered on, weighted by the bytes the
filtering queries were billed and by how well the comparison prunes blocks (equality over ranges
over `LIKE`). Join keys and comparisons against other columns are ignored since they're only
known at run time.

## How grouping works

Each query is parsed with [sqlglot](https://github.com/tobymao/sqlglot) and normalized: literals
become `?`, `IN` lists of any length collapse to `IN (?)`, comments and formatting are dropped.
The normalized text is hashed into a fingerprint. Cache hits are skipped, and so are `SCRIPT`
parent jobs, whose bytes are already counted by their child statements.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
pytest
```

## License

MIT
