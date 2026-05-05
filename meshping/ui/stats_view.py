from __future__ import annotations

from rich.table import Table

from meshping.mesh.coordinator import Coordinator
from meshping.ui.insights import describe_cell, status_label


def render_stats_table(coordinator: Coordinator) -> Table:
    table = Table(expand=True, title="Link Stats")
    table.add_column("Source")
    table.add_column("Target")
    table.add_column("Status")
    table.add_column("p50", justify="right")
    table.add_column("p99", justify="right")
    table.add_column("Loss%", justify="right")
    table.add_column("Stability", justify="right")
    table.add_column("Protocol", justify="right")
    table.add_column("What's Wrong?")
    table.add_column("Last Error")

    node_map = coordinator.node_map()
    profile = coordinator.settings.usage_profile
    cells = sorted(
        coordinator.matrix.iter_cells(),
        key=lambda cell: (
            cell.loss_pct,
            cell.p99 or 0.0,
            cell.p50 or 0.0,
        ),
        reverse=True,
    )
    for cell in cells:
        table.add_row(
            node_map.get(cell.source_id).display_name if cell.source_id in node_map else cell.source_id,
            node_map.get(cell.target_id).display_name if cell.target_id in node_map else cell.target_id,
            status_label(cell, profile),
            f"{cell.p50:.2f}ms" if cell.p50 is not None else "-",
            f"{cell.p99:.2f}ms" if cell.p99 is not None else "-",
            f"{cell.loss_pct:.1f}",
            f"{cell.stability_pct:d}%" if cell.stability_pct is not None else "-",
            cell.protocol_race_note or cell.preferred_ip_version or "-",
            describe_cell(cell, profile),
            cell.last_error or "-",
        )
    return table
