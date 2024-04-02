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
