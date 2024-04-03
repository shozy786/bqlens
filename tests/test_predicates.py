from bqlens.predicates import ColumnUse, analyze


def test_tables_are_fully_qualified():
    shape = analyze("SELECT a FROM web.events JOIN `other-proj.crm.users` u USING (id)", "acme")
    assert shape.tables == {"acme.web.events", "other-proj.crm.users"}


def test_where_and_join_columns_are_filters():
    shape = analyze(
        """
        SELECT e.name, u.email
        FROM web.events AS e
        JOIN crm.users AS u ON u.id = e.user_id
        WHERE e.event_date >= '2024-01-01' AND u.country IN ('PK', 'DE')
        """,
        "acme",
    )
    assert set(shape.filters) == {
        ColumnUse("acme.crm.users", "id", "eq"),
        ColumnUse("acme.web.events", "user_id", "eq"),
        ColumnUse("acme.web.events", "event_date", "range"),
        ColumnUse("acme.crm.users", "country", "eq"),
    }


def test_projection_columns_are_not_filters():
    shape = analyze("SELECT event_date, name FROM web.events", "acme")
    assert shape.filters == []


def test_filters_trace_through_ctes():
    shape = analyze(
        """
        WITH recent AS (SELECT * FROM web.events),
             named AS (SELECT r.event_date AS d, r.name FROM recent AS r)
        SELECT name FROM named WHERE d = '2024-01-01'
        """,
        "acme",
    )
    assert shape.filters == [ColumnUse("acme.web.events", "event_date", "eq")]


def test_filters_on_derived_columns_are_dropped():
    shape = analyze(
        "SELECT * FROM (SELECT DATE(ts) AS d FROM web.events) WHERE d = '2024-01-01'",
        "acme",
    )
    assert shape.filters == []


def test_qualified_star_passes_through():
    shape = analyze(
        "SELECT * FROM (SELECT e.*, u.email FROM web.events e JOIN crm.users u ON u.id = e.uid) WHERE event_date > '2024'",
        "acme",
    )
    assert ColumnUse("acme.web.events", "event_date", "range") in shape.filters


def test_filtered_columns_is_case_insensitive():
    shape = analyze("SELECT 1 FROM web.events WHERE Event_Date = '2024-01-01' AND name LIKE 'x%'", "acme")
    assert shape.filtered_columns("acme.web.events") == {"event_date", "name"}


def test_star_in_outer_query_reads_every_column():
    shape = analyze("SELECT * FROM web.events WHERE event_date = '2024-01-01'", "acme")
    assert shape.star_tables == {"acme.web.events"}


def test_star_inside_cte_is_pruned():
    shape = analyze("WITH e AS (SELECT * FROM web.events) SELECT name FROM e", "acme")
    assert shape.star_tables == set()


def test_star_chain_and_qualified_star():
    shape = analyze(
        """
        WITH e AS (SELECT * FROM web.events)
        SELECT e.*, u.email FROM e JOIN crm.users u ON u.id = e.uid
        """,
        "acme",
    )
    assert shape.star_tables == {"acme.web.events"}


def test_star_except_is_deliberate():
    assert analyze("SELECT * EXCEPT (payload) FROM web.events", "acme").star_tables == set()


def test_star_in_union_branches():
    shape = analyze("SELECT * FROM web.events UNION ALL SELECT * FROM web.events_archive", "acme")
    assert shape.star_tables == {"acme.web.events", "acme.web.events_archive"}


def test_unqualified_column_in_join_is_ambiguous():
    shape = analyze("SELECT 1 FROM web.events e JOIN crm.users u ON u.id = e.uid WHERE event_date = '2024'", "acme")
    assert ("acme.web.events", "event_date") not in {(f.table, f.column) for f in shape.filters}
    assert ("acme.crm.users", "event_date") not in {(f.table, f.column) for f in shape.filters}


def test_unnest_does_not_make_columns_ambiguous():
    shape = analyze(
        """
        SELECT item.sku FROM web.orders, UNNEST(items) AS item, UNNEST(tags) AS tag
        WHERE order_date = '2024-04-01' AND item.qty > 1 AND tag = 'gift'
        """,
        "acme",
    )
    assert shape.filters == [ColumnUse("acme.web.orders", "order_date", "eq")]
