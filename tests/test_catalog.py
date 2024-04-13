from bqlens.catalog import Catalog

from .stubs import StubClient


def test_from_json(fixtures):
    catalog = Catalog.from_json(fixtures / "tables.json")
    assert len(catalog) == 7

    sessions = catalog.get("acme-analytics.web.sessions")
    assert sessions.partitioned
    assert sessions.clustering == ("country",)

    customers = catalog.get("acme-analytics.crm.customers")
    assert not customers.partitioned
    assert customers.clustering == ()

    assert catalog.get("acme-analytics.web.nope") is None


def test_from_bigquery():
    client = StubClient(
        [
            {"id": "p.web.events", "num_columns": 48, "partition_column": "event_date", "clustering": [], "num_bytes": 10},
            {"id": "p.web.sessions", "num_columns": 9, "partition_column": None, "clustering": ["a", "b"], "num_bytes": None},
        ]
    )
    catalog = Catalog.from_bigquery(client, "p", "EU")
    assert "`p`.`region-eu`.INFORMATION_SCHEMA.COLUMNS" in client.queries[0]
    assert catalog.get("p.web.events").partition_column == "event_date"
    assert catalog.get("p.web.sessions").clustering == ("a", "b")
    assert catalog.get("p.web.sessions").num_bytes == 0
