import json
from datetime import datetime, timezone

import pytest

from bqlens.jobs import Job, read_file


def test_reads_jsonl(fixtures):
    jobs = list(read_file(fixtures / "jobs.jsonl"))
    assert len(jobs) == 11
    first = jobs[0]
    assert first.created == datetime(2024, 2, 5, 8, 0, 12, tzinfo=timezone.utc)
    assert first.bytes_billed == 42949672960
    assert first.project == "acme-analytics"
    assert jobs[7].cache_hit is True


def test_reads_json_array(tmp_path, fixtures):
    rows = [json.loads(line) for line in (fixtures / "jobs.jsonl").read_text().splitlines()]
    path = tmp_path / "jobs.json"
    path.write_text("\n  " + json.dumps(rows[:2]))
    assert [j.job_id for j in read_file(path)] == ["bquxjob_01", "bquxjob_02"]


@pytest.mark.parametrize(
    "value",
    ["2024-02-05 08:00:12 UTC", "2024-02-05T08:00:12Z", "2024-02-05T08:00:12.000000+00:00", "1707120012", 1707120012.0],
)
def test_timestamp_formats(value):
    job = Job.from_row({"job_id": "x", "creation_time": value})
    assert job.created == datetime(2024, 2, 5, 8, 0, 12, tzinfo=timezone.utc)
