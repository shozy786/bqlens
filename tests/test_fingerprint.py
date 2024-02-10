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


def test_normalize_output_is_readable():
    assert normalize("select a from ds.t where b = 1") == "SELECT a FROM ds.t WHERE b = ?"
