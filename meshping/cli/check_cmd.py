from __future__ import annotations

import asyncio

import click
from rich.console import Console

from meshping.config.settings import Settings
from meshping.mesh.coordinator import Coordinator

from ._common import combine_target_inputs


@click.command("check")
@click.option("--nodes", required=True, help="Comma-separated host:port targets.")
@click.option("--max-p99", required=True, type=float)
@click.option("--max-loss", required=True, type=float)
@click.option("--samples", default=10, show_default=True, type=int)
@click.option("--interval", default=1.0, show_default=True, type=float)
@click.option("--timeout", default=2.0, show_default=True, type=float)
@click.option("--proxy", help="HTTP CONNECT proxy URL for TCP probing.")
@click.option(
    "--no-proxy",
    is_flag=True,
    help="Disable proxy auto-detection from HTTP_PROXY/HTTPS_PROXY.",
)
def check_command(
    nodes: str,
    max_p99: float,
    max_loss: float,
    samples: int,
    interval: float,
    timeout: float,
    proxy: str | None,
    no_proxy: bool,
) -> None:
    """Run a non-interactive health check and exit non-zero on failure."""
    target_nodes = combine_target_inputs((), nodes, agent=False)
    settings = Settings(
        probe_interval_s=interval,
        probe_timeout_s=timeout,
        history_window=max(samples, 10),
    )
    exit_code = asyncio.run(
        _run_check(
            target_nodes,
            settings=settings,
            samples=samples,
            max_p99=max_p99,
            max_loss=max_loss,
            proxy_url=proxy,
            use_env_proxy=not no_proxy,
        )
    )
    raise SystemExit(exit_code)


async def _run_check(
    nodes,
    *,
    settings: Settings,
    samples: int,
    max_p99: float,
    max_loss: float,
    proxy_url: str | None = None,
    use_env_proxy: bool = True,
) -> int:
    console = Console()
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

    failed = False
    for node in coordinator.nodes:
        cell = coordinator.matrix.get(coordinator.local_node.id, node.id)
        if not cell:
            failed = True
            console.print(f"✗ {node.display_name}:{node.port} no data")
            continue
        p99 = cell.p99 if cell.p99 is not None else float("inf")
        loss = cell.loss_pct
        if p99 > max_p99 or loss > max_loss:
            failed = True
            suffix = f" error={cell.last_error}" if cell.last_error else ""
            console.print(
                f"✗ {node.display_name}:{node.port} p99={p99:.2f}ms loss={loss:.1f}%{suffix}"
            )
        else:
            console.print(
                f"✓ {node.display_name}:{node.port} p99={p99:.2f}ms loss={loss:.1f}%"
            )
    return 1 if failed else 0
