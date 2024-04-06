"""Aggregate job history into cost groups, one per query shape, and attach findings."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from .catalog import Catalog
from .clustering import ClusteringAdvice, recommend
from .fingerprint import fingerprint
from .jobs import Job
from .predicates import analyze
from .rules import Finding, check

TIB = 1024**4
ON_DEMAND_USD_PER_TIB = 6.25


@dataclass
class QueryGroup:
    fingerprint: str
    sample: Job  # the most expensive run; it's the one worth reading
    runs: int = 0
    bytes_billed: int = 0
    users: Counter[str] = field(default_factory=Counter)
    findings: list[Finding] = field(default_factory=list)
    first_seen: datetime = field(init=False)
    last_seen: datetime = field(init=False)

    def __post_init__(self) -> None:
        self.first_seen = self.last_seen = self.sample.created

    def add(self, job: Job) -> None:
        self.runs += 1
        self.bytes_billed += job.bytes_billed
        self.users[job.user] += 1
        self.first_seen = min(self.first_seen, job.created)
        self.last_seen = max(self.last_seen, job.created)
        if job.bytes_billed > self.sample.bytes_billed:
            self.sample = job

    @property
    def avg_bytes(self) -> int:
        return self.bytes_billed // max(self.runs, 1)

    @property
    def cost_usd(self) -> float:
        return self.bytes_billed / TIB * ON_DEMAND_USD_PER_TIB


@dataclass
class Report:
    groups: list[QueryGroup]
    jobs: int
    bytes_billed: int
    clustering: list[ClusteringAdvice] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return self.bytes_billed / TIB * ON_DEMAND_USD_PER_TIB


def group_jobs(jobs: Iterable[Job]) -> list[QueryGroup]:
    """Group jobs by fingerprint, most expensive group first."""
    groups: dict[str, QueryGroup] = {}
    for job in jobs:
        fp = fingerprint(job.query)
        if fp not in groups:
            groups[fp] = QueryGroup(fp, sample=job)
        groups[fp].add(job)
    return sorted(groups.values(), key=lambda g: g.bytes_billed, reverse=True)


def build(jobs: Iterable[Job], catalog: Catalog) -> Report:
    jobs = [j for j in jobs if j.billable]
    groups = group_jobs(jobs)
    usage = []
    for group in groups:
        shape = analyze(group.sample.query, group.sample.project)
        group.findings = check(shape, catalog)
        usage.append((shape, group.bytes_billed))
    return Report(
        groups,
        jobs=len(jobs),
        bytes_billed=sum(j.bytes_billed for j in jobs),
        clustering=recommend(usage, catalog),
    )
