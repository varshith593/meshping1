from __future__ import annotations

from rich.table import Table

from meshping.local.doctor import SplitBrainDiagnosis
from meshping.local.health import LocalHealth, read_local_health
from meshping.local.nic import NICWatcher, default_interface


def render_local_health_table(
    health: LocalHealth | None = None,
    *,
    nic_watcher: NICWatcher | None = None,
    split_brain: SplitBrainDiagnosis | None = None,
) -> Table:
    health = health or read_local_health()
    table = Table(expand=True, title="Local Machine Health")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_column("Status")
    _add_counter(table, "Platform", health.platform, False)
    _add_counter(table, "Interface", health.interface, False)
    _add_counter(
        table,
        "CPU load",
        _load_text(health.cpu_load_1m, health.cpu_load_5m),
        (health.cpu_load_1m or 0.0) > 4.0,
    )
    _add_counter(
        table,
        "Memory used",
        f"{health.memory_used_pct:.0f}%" if health.memory_used_pct is not None else None,
        (health.memory_used_pct or 0.0) > 85.0,
    )
    _add_counter(table, "TX queue len", health.tx_queue_len, False)
    _add_counter(table, "TCP retransmits", health.tcp_retransmits, (health.tcp_retransmits or 0) > 0)
    _add_counter(table, "Sockets used", health.sockets_used, False)
    _add_counter(table, "TIME_WAIT", health.tcp_time_wait, False)
    _add_counter(table, "CLOSE_WAIT", health.tcp_close_wait, (health.tcp_close_wait or 0) > 0)
    _add_counter(table, "TX dropped", health.tx_dropped, (health.tx_dropped or 0) > 0)
    _add_counter(table, "RX missed", health.rx_missed, (health.rx_missed or 0) > 0)
    if split_brain:
        value = (
            f"gw {split_brain.gateway_rtt_ms:.2f}ms / internet {split_brain.internet_rtt_ms:.2f}ms"
            if split_brain.gateway_rtt_ms is not None and split_brain.internet_rtt_ms is not None
            else split_brain.diagnosis
        )
        table.add_row(
            "Split-brain",
            value,
            "[yellow]WARN[/yellow]" if split_brain.diagnosis != "Path healthy" else "[green]OK[/green]",
        )
        table.add_row("Diagnosis", split_brain.diagnosis, "[green]INFO[/green]")
    for metric, value, status in _nic_rows(health.interface, nic_watcher=nic_watcher):
        table.add_row(metric, value, status)
    if health.note:
        table.add_row("Note", health.note, "[yellow]WARN[/yellow]")
    return table


def _add_counter(table: Table, name: str, value: object, warn: bool) -> None:
    status = "[yellow]WARN[/yellow]" if warn else "[green]OK[/green]"
    table.add_row(name, "-" if value is None else str(value), status)


def _load_text(one_min: float | None, five_min: float | None) -> str | None:
    if one_min is None and five_min is None:
        return None
    if one_min is None:
        return f"5m {five_min:.2f}"
    if five_min is None:
        return f"1m {one_min:.2f}"
    return f"1m {one_min:.2f} / 5m {five_min:.2f}"


def _nic_rows(
    interface: str | None,
    *,
    nic_watcher: NICWatcher | None = None,
) -> list[tuple[str, str, str]]:
    iface = interface or default_interface()
    if not iface:
        return []
    watcher = nic_watcher or NICWatcher(interface=iface)
    watcher.sample()
    delta = watcher.latest_delta()
    if delta is None:
        return []
    status = "[yellow]WARN[/yellow]" if delta.tx_dropped_per_sec > 0 else "[green]OK[/green]"
    irq = (
        f"{delta.irq_coalesce_usecs}us"
        if delta.irq_coalesce_usecs is not None
        else "adaptive/unknown"
    )
    return [
        (
            "TX util",
            f"{watcher.tx_utilization_sparkline()} {delta.utilization_tx_pct:.0f}%",
            "[green]OK[/green]",
        ),
        (
            "RX util",
            f"{watcher.rx_utilization_sparkline()} {delta.utilization_rx_pct:.0f}%",
            "[green]OK[/green]",
        ),
        (
            "TX drops/s",
            f"{watcher.tx_drop_sparkline()} {delta.tx_dropped_per_sec:.1f}",
            status,
        ),
        (
            "RX missed/s",
            f"{watcher.rx_miss_sparkline()} {delta.rx_missed_per_sec:.1f}",
            "[yellow]WARN[/yellow]" if delta.rx_missed_per_sec > 0 else "[green]OK[/green]",
        ),
        ("IRQ coalesce", irq, "[green]OK[/green]"),
    ]
