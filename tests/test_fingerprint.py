from bqlens.fingerprint import fingerprint, normalize


def test_literals_do_not_change_fingerprint():
    a = "SELECT user_id FROM ds.events WHERE dt = '2024-01-01' AND n > 5"
    b = "SELECT user_id FROM ds.events WHERE dt = '2024-02-11' AND n > 10"
    assert fingerprint(a) == fingerprint(b)


def test_formatting_and_comments_are_ignored():
    a = "select user_id\n  from ds.events -- daily\n where dt = '2024-01-01'"
    b = "SELECT user_id FROM ds.events WHERE dt = '2024-03-01'"
    assert fingerprint(a) == fingerprint(b)


def test_different_shapes_differ():
    a = "SELECT user_id FROM ds.events WHERE dt = '2024-01-01'"
    b = "SELECT user_id FROM ds.events WHERE country = 'PK'"
    assert fingerprint(a) != fingerprint(b)


def test_in_lists_of_any_length_collapse():
    a = "SELECT * FROM ds.orders WHERE status IN ('new', 'paid')"
    b = "SELECT * FROM ds.orders WHERE status IN ('new', 'paid', 'refunded', 'void')"
    assert fingerprint(a) == fingerprint(b)
    assert "IN (?)" in normalize(a)


def test_in_subquery_is_kept():
    sql = "SELECT * FROM ds.orders WHERE user_id IN (SELECT id FROM ds.users WHERE vip)"
    assert "SELECT id FROM ds.users" in normalize(sql)


def test_normalize_output_is_readable():
    assert normalize("select a from ds.t where b = 1") == "SELECT a FROM ds.t WHERE b = ?"
