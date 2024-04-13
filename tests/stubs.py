"""Minimal stand-in for google.cloud.bigquery.Client."""


class StubClient:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def query(self, sql, **_):
        self.queries.append(sql)
        return self

    def result(self):
        return iter(self.rows)
