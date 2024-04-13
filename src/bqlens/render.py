"""Turn a report into something a person can read."""

from __future__ import annotations

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
        f"about [bold]${report.cost_usd:,.2f}[/] at on-demand rates\n"
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
