from __future__ import annotations

from rich.console import Group
from rich.table import Table
from rich.text import Text

from meshping.models.stress_result import StressResult, StressStatus


def render_stress_table(results: list[StressResult]) -> Table:
    table = Table(expand=True, title="Stress Results")
    table.add_column("Target")
    table.add_column("Protocol")
    table.add_column("Requested", justify="right")
    table.add_column("Achieved", justify="right")
    table.add_column("p50", justify="right")
    table.add_column("p99", justify="right")
    table.add_column("Degrade", justify="right")
    table.add_column("Loss", justify="right")
    table.add_column("OK/Attempted", justify="right")
    table.add_column("Spark")
    table.add_column("NIC")
    table.add_column("Status")
    for result in results:
        table.add_row(
            result.target or "-",
            result.protocol,
            str(result.requested_pps or result.load_level_pps),
            f"{result.achieved_pps:.1f}/s" if result.achieved_pps is not None else "-",
            f"{result.p50_rtt:.2f}ms" if result.p50_rtt is not None else "-",
            f"{result.p99_rtt:.2f}ms" if result.p99_rtt is not None else "-",
            f"{result.degradation_pct:.0f}%" if result.degradation_pct is not None else "-",
            f"{result.loss_pct:.1f}%",
            f"{result.succeeded}/{result.attempted}",
            result.sparkline or ("bufferbloat" if result.bufferbloat_detected else "-"),
            str(result.nic_saturated_at) if result.nic_saturated_at is not None else "-",
            _status(result.status),
        )
    return table


def render_ramp_result(results: list[StressResult]) -> Group:
    table = render_stress_table(results)
    first_degrading = next(
        (result.load_level_pps for result in results if result.status == StressStatus.DEGRADING),
        None,
    )
    first_breaking = next(
        (result.load_level_pps for result in results if result.status == StressStatus.BREAKING),
        None,
    )
    safe_limit = None
    for result in results:
        if result.status == StressStatus.HEALTHY:
            safe_limit = result.load_level_pps
    notes = []
    if first_breaking is not None:
        notes.append(f"Breaking point: {first_breaking} pkt/s")
    if first_degrading is not None:
        notes.append(f"Degradation starts: {first_degrading} pkt/s")
    if safe_limit is not None:
        notes.append(f"Safe operating limit: {safe_limit} pkt/s")
    if _bufferbloat_signature(results):
        notes.append("Bufferbloat signature detected across degrading levels.")
    return Group(table, Text(" | ".join(notes), style="yellow" if notes else "dim"))


def render_ramp_chart(results: list[StressResult]) -> Table:
    chart = Table(expand=True, title="Stress Ramp Chart")
    chart.add_column("Load")
    chart.add_column("Bar")
    chart.add_column("p99", justify="right")
    maximum = max((result.p99_rtt or result.avg_rtt or 0.0) for result in results) or 1.0
    for result in results:
        value = result.p99_rtt or result.avg_rtt or 0.0
        width = max(1, int((value / maximum) * 24))
        style = (
            "green"
            if result.status == StressStatus.HEALTHY
            else "yellow"
            if result.status == StressStatus.DEGRADING
            else "red"
        )
        chart.add_row(
            str(result.load_level_pps),
            f"[{style}]{'█' * width}[/{style}]",
            f"{value:.2f}ms",
        )
    return chart


def _status(status: StressStatus) -> str:
    if status == StressStatus.BREAKING:
        return "[red]BREAKING[/red]"
    if status == StressStatus.DEGRADING:
        return "[yellow]DEGRADING[/yellow]"
    return "[green]HEALTHY[/green]"


def _bufferbloat_signature(results: list[StressResult]) -> bool:
    degrading = [result for result in results if result.status == StressStatus.DEGRADING]
    if len(degrading) < 3:
        return False
    p99s = [result.p99_rtt for result in degrading if result.p99_rtt is not None]
    losses = [result.loss_pct for result in degrading]
    if len(p99s) < 3:
        return False
    return p99s == sorted(p99s) and max(losses) < 2.0
