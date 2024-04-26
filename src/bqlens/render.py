"""Turn a report into something a person can read."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

from .fingerprint import normalize
from .report import Report

_SEVERITY_STYLE = {"high": "bold red", "medium": "yellow", "low": "dim"}


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PiB"


def one_line(sql: str, width: int = 80) -> str:
    text = " ".join(normalize(sql).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def to_console(report: Report, console: Console, top: int = 15) -> None:
    console.print(
        f"[bold]{report.jobs}[/] jobs, [bold]{fmt_bytes(report.bytes_billed)}[/] billed, "
        f"about [bold]${report.cost_usd:,.2f}[/] at ${report.usd_per_tib:g}/TiB\n"
    )

    table = Table(show_lines=False, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("cost", justify="right")
    table.add_column("runs", justify="right")
    table.add_column("per run", justify="right")
    table.add_column("users", justify="right")
    table.add_column("query", overflow="fold", ratio=1)
    groups = report.groups[:top]
    for i, g in enumerate(groups, 1):
        flag = " [red]●[/]" if g.findings else ""
        table.add_row(
            str(i), f"${g.cost_usd:,.2f}", str(g.runs), fmt_bytes(g.avg_bytes), str(len(g.users)),
            one_line(g.sample.query) + flag,
        )
    console.print(table)

    flagged = [(i, g) for i, g in enumerate(groups, 1) if g.findings]
    if flagged:
        console.print("\n[bold]Findings[/]")
    for i, g in flagged:
        console.print(f"\n[bold]#{i}[/] [dim]{g.fingerprint} · sample job {g.sample.job_id}[/]")
        for f in g.findings:
            where = f" [cyan]{f.table}[/]" if f.table else ""
            console.print(f"  [{_SEVERITY_STYLE[f.severity]}]{f.rule}[/]{where}: {f.message}")

    if report.clustering:
        console.print("\n[bold]Clustering[/]")
    for advice in report.clustering:
        current = ", ".join(advice.current) or "none"
        console.print(
            f"\n  [cyan]{advice.table}[/] (currently: {current})\n"
            f"  CLUSTER BY [bold]{', '.join(advice.suggested)}[/] would help "
            f"{advice.coverage:.0%} of the {fmt_bytes(advice.bytes_total)} read from it"
        )


def to_dict(report: Report, top: int | None = None) -> dict[str, Any]:
    return {
        "jobs": report.jobs,
        "bytes_billed": report.bytes_billed,
        "cost_usd": round(report.cost_usd, 2),
        "usd_per_tib": report.usd_per_tib,
        "groups": [
            {
                "fingerprint": g.fingerprint,
                "runs": g.runs,
                "bytes_billed": g.bytes_billed,
                "cost_usd": round(g.cost_usd, 2),
                "users": dict(g.users.most_common()),
                "first_seen": g.first_seen.isoformat(),
                "last_seen": g.last_seen.isoformat(),
                "sample_job_id": g.sample.job_id,
                "query": normalize(g.sample.query),
                "findings": [
                    {"rule": f.rule, "severity": f.severity, "table": f.table, "message": f.message}
                    for f in g.findings
                ],
            }
            for g in report.groups[:top]
        ],
        "clustering": [
            {
                "table": a.table,
                "current": list(a.current),
                "suggested": list(a.suggested),
                "coverage": round(a.coverage, 3),
                "bytes_total": a.bytes_total,
            }
            for a in report.clustering
        ],
    }


def to_markdown(report: Report, top: int = 15) -> str:
    """A report that pastes cleanly into a GitHub issue, Jira ticket or Confluence page."""
    lines = [
        f"**{report.jobs}** jobs, **{fmt_bytes(report.bytes_billed)}** billed, "
        f"about **${report.cost_usd:,.2f}** at ${report.usd_per_tib:g}/TiB",
        "",
        "| # | cost | runs | per run | query | findings |",
        "|--:|-----:|-----:|--------:|-------|----------|",
    ]
    for i, g in enumerate(report.groups[:top], 1):
        # double backticks so BigQuery's own `quoted.names` don't end the code span
        query = one_line(g.sample.query, 100).replace("|", "\\|")
        rules = ", ".join(sorted({f.rule for f in g.findings})) or "–"
        lines.append(f"| {i} | ${g.cost_usd:,.2f} | {g.runs} | {fmt_bytes(g.avg_bytes)} | `` {query} `` | {rules} |")

    flagged = [(i, g) for i, g in enumerate(report.groups[:top], 1) if g.findings]
    if flagged:
        lines += ["", "### Findings"]
    for i, g in flagged:
        lines += ["", f"**#{i}** (`{g.fingerprint}`, sample job `{g.sample.job_id}`)", ""]
        lines += [f"- **{f.rule}** `{f.table}`: {f.message}" for f in g.findings]

    if report.clustering:
        lines += ["", "### Clustering", ""]
    for a in report.clustering:
        lines.append(
            f"- `{a.table}`: `CLUSTER BY {', '.join(a.suggested)}` "
            f"(currently {', '.join(a.current) or 'none'}) would help {a.coverage:.0%} of "
            f"{fmt_bytes(a.bytes_total)} read"
        )
    return "\n".join(lines) + "\n"
