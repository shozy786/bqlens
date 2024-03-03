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


def test_filtered_columns_is_case_insensitive():
    shape = analyze("SELECT 1 FROM web.events WHERE Event_Date = '2024-01-01' AND name LIKE 'x%'", "acme")
    assert shape.filtered_columns("acme.web.events") == {"event_date", "name"}
