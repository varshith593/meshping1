from __future__ import annotations

from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from meshping.models.cluster import Cluster


def render_cluster_table(clusters: list[Cluster]) -> Table:
    table = Table(expand=True, title="Topology Clusters")
    table.add_column("Cluster")
    table.add_column("Color")
    table.add_column("Nodes")
    for cluster in clusters:
        table.add_row(
            cluster.id,
            f"[{cluster.color}]{cluster.color}[/{cluster.color}]",
            ", ".join(cluster.node_ids),
        )
    return table


def render_topology_diagram(
    clusters: list[Cluster],
    *,
    inter_cluster_latency: dict[tuple[str, str], float] | None = None,
) -> Group:
    if len(clusters) < 2:
        return Group(
            Panel(
                "\n".join(clusters[0].node_ids) if clusters else "No clusters yet",
                title=clusters[0].id if clusters else "Clusters",
                border_style=clusters[0].color if clusters else "dim",
            )
        )
    panels = [
        Panel(
            "\n".join(cluster.node_ids) or "No nodes",
            title=cluster.id,
            border_style=cluster.color,
        )
        for cluster in clusters[:2]
    ]
    left = clusters[0]
    right = clusters[1]
    latency = None
    if inter_cluster_latency:
        latency = inter_cluster_latency.get((left.id, right.id)) or inter_cluster_latency.get(
            (right.id, left.id)
        )
    middle = Panel(
        Text(
            f"{latency:.1f}ms\n◄────────►" if latency is not None else "◄────────►",
            justify="center",
        ),
        border_style="dim",
        title="Link",
    )
    extras = []
    if len(clusters) > 2:
        extra_table = Table(expand=True, title="Other Cluster Links")
        extra_table.add_column("Pair")
        extra_table.add_column("Latency", justify="right")
        for left_cluster in clusters:
            for right_cluster in clusters:
                if left_cluster.id >= right_cluster.id:
                    continue
                value = None
                if inter_cluster_latency:
                    value = inter_cluster_latency.get((left_cluster.id, right_cluster.id))
                extra_table.add_row(
                    f"{left_cluster.id} <-> {right_cluster.id}",
                    f"{value:.1f}ms" if value is not None else "-",
                )
        extras.append(extra_table)
    return Group(Columns([panels[0], middle, panels[1]], expand=True), *extras)
