from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.table import Table

from meshping.config.settings import Settings
from meshping.mesh.coordinator import Coordinator
from meshping.ui.insights import describe_cell, status_label

from ._common import combine_target_inputs


@click.command("diff")
@click.argument("left")
@click.argument("right")
@click.option("--samples", default=6, show_default=True, type=int)
@click.option("--interval", default=0.5, show_default=True, type=float)
@click.option("--timeout", default=2.0, show_default=True, type=float)
@click.option("--proxy", help="HTTP CONNECT proxy URL for TCP probing.")
@click.option(
    "--no-proxy",
    is_flag=True,
    help="Disable proxy auto-detection from HTTP_PROXY/HTTPS_PROXY.",
)
def diff_command(
    left: str,
    right: str,
    samples: int,
    interval: float,
    timeout: float,
    proxy: str | None,
    no_proxy: bool,
) -> None:
    """Compare two paths side by side."""
    nodes = combine_target_inputs((left, right), None)
    settings = Settings(
        probe_interval_s=interval,
        probe_timeout_s=timeout,
        history_window=max(samples, 20),
    )
    console = Console()
    console.print(
        asyncio.run(
            _run_diff(
                nodes,
                settings=settings,
                samples=samples,
                proxy_url=proxy,
                use_env_proxy=not no_proxy,
            )
        )
    )


async def _run_diff(
    nodes,
    *,
    settings: Settings,
    samples: int,
    proxy_url: str | None,
    use_env_proxy: bool,
):
    coordinator = Coordinator(
        nodes=list(nodes),
        settings=settings,
        proxy_url=proxy_url,
        use_env_proxy=use_env_proxy,
    )
    for index in range(samples):
        await coordinator.run_probe_cycle()
        if index < samples - 1:
            await asyncio.sleep(settings.probe_interval_s)
    table = Table(title="meshping diff", expand=True)
    table.add_column("Target")
    table.add_column("Status")
    table.add_column("p50", justify="right")
    table.add_column("Loss", justify="right")
    table.add_column("What's Wrong?")
    comparisons = []
    for node in nodes:
        cell = coordinator.matrix.get(coordinator.local_node.id, node.id)
        comparisons.append((node, cell))
        table.add_row(
            node.display_name,
            status_label(cell) if cell else "WAIT",
            f"{cell.p50:.2f}ms" if cell and cell.p50 is not None else "-",
            f"{cell.loss_pct:.1f}%" if cell else "-",
            describe_cell(cell) if cell else "Waiting for samples",
        )
    verdict = _compare(comparisons)
    table.caption = verdict
    coordinator.stop()
    return table


def _compare(comparisons) -> str:
    if len(comparisons) != 2:
        return "Need exactly two targets."
    (left_node, left_cell), (right_node, right_cell) = comparisons
    if not left_cell or not right_cell or left_cell.p50 is None or right_cell.p50 is None:
        return "Not enough data to compare both paths yet."
    if left_cell.loss_pct > right_cell.loss_pct:
        return f"{right_node.display_name} is cleaner; {left_node.display_name} is losing more packets."
    if right_cell.loss_pct > left_cell.loss_pct:
        return f"{left_node.display_name} is cleaner; {right_node.display_name} is losing more packets."
    delta = abs(left_cell.p50 - right_cell.p50)
    if left_cell.p50 < right_cell.p50:
        return f"{left_node.display_name} is faster by {delta:.2f}ms."
    if right_cell.p50 < left_cell.p50:
        return f"{right_node.display_name} is faster by {delta:.2f}ms."
    return "Both paths look effectively the same right now."
