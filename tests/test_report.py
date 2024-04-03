import pytest

from bqlens.catalog import Catalog
from bqlens.jobs import read_file
from bqlens.report import TIB, build, group_jobs


@pytest.fixture
def jobs(fixtures):
    return list(read_file(fixtures / "jobs.jsonl"))


def test_groups_runs_of_the_same_query(jobs):
    groups = group_jobs(jobs)
    dashboard = next(g for g in groups if g.runs == 3)
    assert dashboard.sample.job_id == "bquxjob_03"
    assert dashboard.users == {"looker@acme-analytics.iam.gserviceaccount.com": 3}
    assert dashboard.first_seen < dashboard.last_seen


def test_most_expensive_group_first(jobs):
    top = group_jobs(jobs)[0]
    assert top.runs == 2
    assert "user_id" in top.sample.query
    assert top.sample.job_id == "bquxjob_05"  # the bigger of the two runs
    assert top.cost_usd == pytest.approx(top.bytes_billed / TIB * 6.25)


def test_cache_hits_and_script_parents_are_not_double_counted(jobs):
    report = build(jobs, Catalog())
    assert report.jobs == 9
    ids = {g.sample.job_id for g in report.groups}
    assert "script_job_09" not in ids and "script_job_09_0" in ids
    ga4 = next(g for g in report.groups if "ga4" in g.sample.query)
    assert ga4.runs == 1
