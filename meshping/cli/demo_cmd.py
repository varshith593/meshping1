from __future__ import annotations

import asyncio
import contextlib

import click
from rich.console import Console

from meshping.config.settings import Settings
from meshping.demo import DEMO_COORDINATOR, demo_agent_nodes, demo_service_nodes, render_demo_table
from meshping.demo.stack import DemoStack
from meshping.mesh.coordinator import Coordinator
from meshping.ui.matrix_view import MeshDashboard

from ._common import ensure_export_path, parse_listen


@click.command("demo")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--listen", default=DEMO_COORDINATOR, show_default=True)
@click.option("--interval", default=1.0, show_default=True, type=float)
@click.option("--refresh", default=1.0, show_default=True, type=float)
@click.option("--profile", default="work", show_default=True, type=click.Choice(["work", "gaming", "video"]))
@click.option("--record", "record_path", help="Record this demo matrix to a .mpr replay file.")
@click.option("--log", "log_path", help="Write demo history to a SQLite file.")
def demo_command(
    host: str,
    listen: str,
    interval: float,
    refresh: float,
    profile: str,
    record_path: str | None,
    log_path: str | None,
) -> None:
    """Run the local 8-service demo and open the full adjacency matrix."""
    listen_host, listen_port = parse_listen(listen)
    settings = Settings(
        probe_interval_s=interval,
        refresh_rate_s=refresh,
        usage_profile=profile,
        cluster_threshold_ms=3.5,
        asymmetry_threshold=4.0,
    )
    console = Console()
    console.print(render_demo_table(host))
    console.print("Demo services run on localhost ports 18080-18087.")
    targets = " ".join(f"{node.name}={host}:{node.port}" for node in demo_service_nodes(host))
    console.print(f"Service-port matrix: python3 -m meshping mesh {targets}")
    asyncio.run(
        _run_demo(
            demo_agent_nodes(host),
            host=host,
            listen_host=listen_host,
            listen_port=listen_port,
            settings=settings,
            record_path=ensure_export_path(record_path),
            history_path=ensure_export_path(log_path),
        )
    )


async def _run_demo(
    nodes,
    *,
    host: str,
    listen_host: str,
    listen_port: int,
    settings: Settings,
    record_path,
    history_path,
) -> None:
    console = Console()
    stack = DemoStack(
        host=host,
        coordinator_host=listen_host,
        coordinator_port=listen_port,
        interval_s=settings.probe_interval_s,
    )
    coordinator = Coordinator(
        nodes=list(nodes),
        settings=settings,
        record_path=record_path,
        history_path=history_path,
    )
    dashboard = MeshDashboard(console=console, show_local=False)
    stack_task = asyncio.create_task(stack.run_forever())
    worker = asyncio.create_task(
        coordinator.run_distributed(
            listen_host=listen_host,
            listen_port=listen_port,
            push_config=False,
        )
    )
    try:
        await asyncio.sleep(0.1)
        await dashboard.run(coordinator)
    finally:
        coordinator.stop()
        stack_task.cancel()
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await stack_task
        with contextlib.suppress(asyncio.CancelledError):
            await worker
