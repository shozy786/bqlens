# Changelog

## 0.2.0 (2024-05-12)

- `lint` command for checking SQL files (or stdin) in CI, with `--fail-on`
- `repeated-scan`: expensive queries rerunning many times a day
- `--usd-per-tib` / `BQLENS_USD_PER_TIB` for regional on-demand prices or editions rates
- JSON and markdown output
- Ingestion-time partitioned tables (`_PARTITIONTIME`, `_PARTITIONDATE`)
- Wildcard tables and the `unbounded-wildcard` rule
- `wrapped-partition-filter`: partition column only filtered through a function
- `dataset.table` references resolve when only one project in the catalog has that table
- Queries sqlglot can't parse are grouped by text instead of aborting the report

## 0.1.0 (2024-04-13)

- Group job history by query fingerprint and rank by bytes billed
- `missing-partition-filter`, `select-star` and `limit-without-filter` rules
- Clustering suggestions weighted by bytes billed
- `analyze` for exported job history, `scan` for live INFORMATION_SCHEMA
