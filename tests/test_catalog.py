from bqlens.catalog import Catalog


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
