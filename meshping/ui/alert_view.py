from __future__ import annotations

from rich.table import Table

from meshping.mesh.coordinator import Coordinator
from meshping.ui.theme import severity_style


def render_alerts_table(
    coordinator: Coordinator,
    *,
    muted_targets: set[str] | None = None,
) -> Table:
    table = Table(expand=True, title="Alerts")
    table.add_column("Severity")
    table.add_column("Type")
    table.add_column("Path")
    table.add_column("Message")

    alerts = sorted(
        [
            alert
            for alert in coordinator.alerts
            if not muted_targets or alert.target_id not in muted_targets
        ],
        key=lambda alert: alert.detected_at,
        reverse=True,
    )
    for alert in alerts:
        table.add_row(
            f"[{severity_style(alert.severity)}]{alert.severity}[/{severity_style(alert.severity)}]",
            alert.alert_type,
            f"{alert.source_id}->{alert.target_id}",
            alert.message,
        )
    return table
