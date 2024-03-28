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
