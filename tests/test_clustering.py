import pytest

from bqlens.catalog import Catalog, Table
from bqlens.clustering import recommend
from bqlens.predicates import analyze

GIB = 1024**3


@pytest.fixture
def catalog():
    return Catalog(
        [
            Table("p.web.events", partition_column="event_date", num_bytes=2000 * GIB),
            Table("p.web.sessions", partition_column="day", clustering=("country",), num_bytes=200 * GIB),
            Table("p.crm.users", num_bytes=GIB // 2),
        ]
    )


def usage(*pairs):
    return [(analyze(sql, "p"), billed) for sql, billed in pairs]


def test_ranks_columns_by_weighted_bytes(catalog):
    advice = recommend(
        usage(
            ("SELECT 1 FROM web.events WHERE event_date = '2024' AND user_id = 'u'", 500 * GIB),
            ("SELECT 1 FROM web.events WHERE event_date = '2024' AND event_name IN ('a')", 100 * GIB),
            ("SELECT 1 FROM web.events WHERE event_date = '2024' AND ts > '2024'", 150 * GIB),
            ("SELECT 1 FROM web.events WHERE event_date = '2024'", 250 * GIB),
        ),
        catalog,
    )
    (events,) = advice
    assert events.suggested == ("user_id", "event_name", "ts")  # 500, 100*1.0, 150*0.6 -> ts after event_name
    assert events.bytes_total == 1000 * GIB
    assert events.coverage == pytest.approx(0.75)


def test_partition_column_is_never_suggested(catalog):
    advice = recommend(usage(("SELECT 1 FROM web.events WHERE event_date = '2024'", GIB)), catalog)
    assert advice == []


def test_existing_clustering_that_matches_is_left_alone(catalog):
    sql = "SELECT 1 FROM web.sessions WHERE day = '2024' AND country = 'PK' AND device LIKE 'ip%'"
    assert recommend(usage((sql, 50 * GIB)), catalog) == []


def test_small_tables_are_skipped(catalog):
    assert recommend(usage(("SELECT 1 FROM crm.users WHERE email = 'x'", GIB)), catalog) == []


def test_join_bytes_are_split_by_table_size(catalog):
    sql = """
        SELECT 1 FROM web.events e JOIN crm.users u ON u.id = e.user_id
        WHERE e.event_date = '2024' AND u.country = 'PK'
    """
    (events,) = recommend(usage((sql, 100 * GIB)), catalog)
    assert events.suggested == ("user_id",)
    assert events.bytes_total == pytest.approx(100 * GIB * 2000 / 2000.5, rel=1e-6)
