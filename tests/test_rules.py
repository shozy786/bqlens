import pytest

from bqlens.catalog import Catalog
from bqlens.predicates import analyze
from bqlens.rules import check


@pytest.fixture
def catalog(fixtures):
    return Catalog.from_json(fixtures / "tables.json")


def findings(sql, catalog):
    return {(f.rule, f.table) for f in check(analyze(sql, "acme-analytics"), catalog)}


def test_missing_partition_filter(catalog):
    assert findings("SELECT * FROM web.events WHERE user_id = 'u1'", catalog) >= {
        ("missing-partition-filter", "acme-analytics.web.events")
    }


def test_partition_filter_present(catalog):
    sql = "SELECT name FROM web.events WHERE event_date = '2024-01-01'"
    assert ("missing-partition-filter", "acme-analytics.web.events") not in findings(sql, catalog)


def test_partition_filter_through_cte(catalog):
    sql = "WITH e AS (SELECT * FROM web.events) SELECT name FROM e WHERE event_date > '2024-01-01'"
    assert ("missing-partition-filter", "acme-analytics.web.events") not in findings(sql, catalog)


def test_unpartitioned_and_unknown_tables_are_ignored(catalog):
    assert findings("SELECT id FROM crm.customers", catalog) == set()
    assert findings("SELECT id FROM somewhere.unknown", catalog) == set()


def test_select_star_on_wide_table(catalog):
    found = check(analyze("SELECT * FROM crm.customers WHERE id = 1", "acme-analytics"), catalog)
    star = next(f for f in found if f.rule == "select-star")
    assert star.table == "acme-analytics.crm.customers"
    assert "31 columns" in star.message


def test_select_star_on_unknown_table_still_flagged(catalog):
    assert ("select-star", "acme-analytics.ds.mystery") in findings("SELECT * FROM ds.mystery", catalog)


def test_limit_on_unclustered_table(catalog):
    assert ("limit-without-filter", "acme-analytics.crm.customers") in findings(
        "SELECT * FROM crm.customers LIMIT 100", catalog
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id FROM crm.customers WHERE country = 'PK' LIMIT 100",
        "SELECT country, COUNT(*) FROM crm.customers GROUP BY 1 LIMIT 10",
        "SELECT session_id FROM web.sessions LIMIT 10",  # clustered
    ],
)
def test_limit_cases_that_are_fine(catalog, sql):
    assert not any(rule == "limit-without-filter" for rule, _ in findings(sql, catalog))


def test_wildcard_without_table_suffix(catalog):
    found = check(analyze("SELECT event_name FROM `acme-analytics.ga4.events_*`", "acme-analytics"), catalog)
    (wildcard,) = [f for f in found if f.rule == "unbounded-wildcard"]
    assert "all 3 tables" in wildcard.message


def test_wildcard_with_table_suffix(catalog):
    sql = "SELECT event_name FROM `acme-analytics.ga4.events_*` WHERE _TABLE_SUFFIX BETWEEN '20240101' AND '20240102'"
    assert not any(rule == "unbounded-wildcard" for rule, _ in findings(sql, catalog))


@pytest.mark.parametrize(
    "where, expected",
    [
        ("FORMAT_DATE('%Y%m', event_date) = '202401'", True),
        ("CAST(event_date AS STRING) LIKE '2024-01%'", True),
        ("DATE_TRUNC(event_date, MONTH) = '2024-01-01'", False),
        ("event_date = '2024-01-01'", False),
        ("CAST(event_date AS STRING) = '2024-01-01' OR event_date = '2024-01-02'", False),
    ],
)
def test_wrapped_partition_filter(catalog, where, expected):
    found = findings(f"SELECT name FROM web.events WHERE {where}", catalog)
    assert (("wrapped-partition-filter", "acme-analytics.web.events") in found) is expected
    assert ("missing-partition-filter", "acme-analytics.web.events") not in found


@pytest.mark.parametrize("pseudo", ["_PARTITIONTIME", "_PARTITIONDATE"])
def test_ingestion_time_pseudo_columns_count(catalog, pseudo):
    sql = f"SELECT payload FROM web.raw_hits WHERE {pseudo} >= '2024-04-01'"
    assert not any(rule.endswith("partition-filter") for rule, _ in findings(sql, catalog))


def test_ingestion_time_without_filter(catalog):
    assert ("missing-partition-filter", "acme-analytics.web.raw_hits") in findings(
        "SELECT payload FROM web.raw_hits WHERE payload LIKE '%x%'", catalog
    )
