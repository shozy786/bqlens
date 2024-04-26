import json

import pytest
from click.testing import CliRunner

from bqlens.cli import main


def test_analyze_end_to_end(fixtures):
    result = CliRunner().invoke(
        main,
        ["analyze", str(fixtures / "jobs.jsonl"), "--catalog", str(fixtures / "tables.json")],
        terminal_width=200,
    )
    assert result.exit_code == 0, result.output
    assert "9 jobs" in result.output
    assert "missing-partition-filter" in result.output
    assert "acme-analytics.web.events" in result.output
    assert "CLUSTER BY user_id, event_name" in result.output


@pytest.fixture
def run(fixtures):
    def run(*args):
        result = CliRunner().invoke(
            main, ["analyze", str(fixtures / "jobs.jsonl"), "--catalog", str(fixtures / "tables.json"), *args]
        )
        assert result.exit_code == 0, result.output
        return result.output

    return run


def test_json_output(run):
    data = json.loads(run("--format", "json", "--top", "3"))
    assert data["jobs"] == 9
    assert len(data["groups"]) == 3
    assert data["groups"][0]["findings"][0]["rule"] == "missing-partition-filter"
    assert data["clustering"][0]["suggested"] == ["user_id", "event_name"]


def test_markdown_output(run):
    out = run("--format", "markdown")
    assert out.startswith("**9** jobs")
    assert "| 1 | $30.01 | 2 | 2.40 TiB |" in out
    assert "### Clustering" in out


def test_lint_files_and_exit_code(tmp_path, fixtures):
    bad = tmp_path / "bad.sql"
    bad.write_text("SELECT * FROM web.events WHERE user_id = 'x'")
    good = tmp_path / "good.sql"
    good.write_text("SELECT name FROM web.events WHERE event_date = '2024-04-01'")
    args = ["lint", "--catalog", str(fixtures / "tables.json"), "--project", "acme-analytics"]

    result = CliRunner().invoke(main, [*args, str(good), str(bad)])
    assert result.exit_code == 1
    assert f"{bad}: high missing-partition-filter acme-analytics.web.events" in result.output
    assert str(good) not in result.output

    assert CliRunner().invoke(main, [*args, "--fail-on", "never", str(bad)]).exit_code == 0


def test_lint_reads_stdin(fixtures):
    result = CliRunner().invoke(
        main,
        ["lint", "--catalog", str(fixtures / "tables.json"), "--project", "acme-analytics", "--fail-on", "medium"],
        input="SELECT * FROM crm.customers LIMIT 5",
    )
    assert result.exit_code == 1
    assert "<stdin>: medium limit-without-filter" in result.output


def test_custom_price(run):
    data = json.loads(run("--format", "json", "--usd-per-tib", "8.13"))
    assert data["usd_per_tib"] == 8.13
    assert data["groups"][0]["cost_usd"] == pytest.approx(39.04, abs=0.01)
