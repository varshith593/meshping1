from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import click
from rich.console import Console

from meshping.config.settings import Settings
from meshping.mesh.coordinator import Coordinator
from meshping.ui.matrix_view import MeshDashboard

from ._common import combine_target_inputs, ensure_export_path, parse_listen


@click.command("mesh")
@click.argument("targets", nargs=-1)
@click.option("--nodes", help="Comma-separated TCP targets.")
@click.option("--agents", help="Comma-separated agent targets for distributed mode.")
@click.option("--distributed", is_flag=True, help="Collect reports from remote agents.")
@click.option("--listen", default="0.0.0.0:7778", show_default=True)
@click.option("--public-host", help="Coordinator address reachable by remote agents.")
@click.option("--interval", default=1.0, show_default=True, type=float)
@click.option("--timeout", default=2.0, show_default=True, type=float)
@click.option("--history-window", default=100, show_default=True, type=int)
@click.option("--profile", default="work", show_default=True, type=click.Choice(["work", "gaming", "video"]))
@click.option("--spike-factor", default=3.0, show_default=True, type=float)
@click.option("--loss-threshold", default=5.0, show_default=True, type=float)
@click.option("--cluster-threshold", default=5.0, show_default=True, type=float)
@click.option("--asymmetry-threshold", default=2.0, show_default=True, type=float)
@click.option("--refresh", default=1.0, show_default=True, type=float)
@click.option("--export", "export_path", help="Write JSON snapshots to a file.")
@click.option("--record", "record_path", help="Record this session to a .mpr replay file.")
@click.option("--log", "log_path", help="Write session history to a SQLite file.")
@click.option("--proxy", help="HTTP CONNECT proxy URL for agentless TCP probing.")
@click.option(
    "--no-proxy",
    is_flag=True,
    help="Disable proxy auto-detection from HTTP_PROXY/HTTPS_PROXY.",
)
@click.option("--once", is_flag=True, help="Run one probe cycle and print a static view.")
def mesh_command(
    targets: tuple[str, ...],
    nodes: str | None,
    agents: str | None,
    distributed: bool,
    listen: str,
    public_host: str | None,
    interval: float,
    timeout: float,
    history_window: int,
    profile: str,
    spike_factor: float,
    loss_threshold: float,
    cluster_threshold: float,
    asymmetry_threshold: float,
    refresh: float,
    export_path: str | None,
    record_path: str | None,
    log_path: str | None,
    proxy: str | None,
    no_proxy: bool,
    once: bool,
) -> None:
    """Run the live mesh matrix."""
    target_nodes = combine_target_inputs(
        targets,
        agents if distributed else nodes,
        agent=distributed,
        use_sandbox_defaults=not distributed,
        env_var="MESHPING_AGENTS" if distributed else None,
    )
    if not target_nodes:
        raise click.UsageError("Provide targets or set MESHPING_AGENTS for distributed mode")

    settings = Settings(
        probe_interval_s=interval,
        probe_timeout_s=timeout,
        history_window=history_window,
        usage_profile=profile,
        anomaly_spike_factor=spike_factor,
        anomaly_loss_pct=loss_threshold,
        cluster_threshold_ms=cluster_threshold,
        asymmetry_threshold=asymmetry_threshold,
        refresh_rate_s=refresh,
    )
    asyncio.run(
        _run_mesh(
            target_nodes,
            settings=settings,
            distributed=distributed,
            listen=listen,
            public_host=public_host,
            export_path=ensure_export_path(export_path),
            record_path=ensure_export_path(record_path),
            history_path=ensure_export_path(log_path),
            proxy_url=proxy,
            use_env_proxy=not no_proxy,
            once=once,
            show_local=False,
        )
    )


async def _run_mesh(
    nodes,
    *,
    settings: Settings,
    distributed: bool,
    listen: str,
    public_host: str | None,
    export_path: Path | None,
    record_path: Path | None,
    history_path: Path | None,
    proxy_url: str | None,
    use_env_proxy: bool,
    once: bool,
    show_local: bool,
) -> None:
    console = Console()
    coordinator = Coordinator(
        nodes=list(nodes),
        settings=settings,
        export_path=export_path,
        record_path=record_path,
        history_path=history_path,
        proxy_url=proxy_url,
        use_env_proxy=use_env_proxy,
    )

    try:
        if once:
            if distributed:
                raise click.UsageError("--once is only supported for agentless mode")
            await coordinator.run_probe_cycle()
            console.print(MeshDashboard(console=console).render(coordinator))
            return

        dashboard = MeshDashboard(console=console, show_local=show_local)
        if distributed:
            listen_host, listen_port = parse_listen(listen)
            worker = asyncio.create_task(
                coordinator.run_distributed(
                    listen_host=listen_host,
                    listen_port=listen_port,
                    public_host=public_host,
                    push_config=True,
                )
            )
        else:
            worker = asyncio.create_task(coordinator.run_agentless())

        try:
            await dashboard.run(coordinator)
        finally:
            coordinator.stop()
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
    finally:
        coordinator.stop()


def run_mesh_session(
    nodes,
    *,
    distributed: bool = False,
    listen: str = "0.0.0.0:7778",
    public_host: str | None = None,
    export_path: Path | None = None,
    record_path: Path | None = None,
    history_path: Path | None = None,
    proxy_url: str | None = None,
    use_env_proxy: bool = True,
    once: bool = False,
    show_local: bool = False,
    settings: Settings | None = None,
) -> None:
    asyncio.run(
        _run_mesh(
            nodes,
            settings=settings or Settings(),
            distributed=distributed,
            listen=listen,
            public_host=public_host,
            export_path=export_path,
            record_path=record_path,
            history_path=history_path,
            proxy_url=proxy_url,
            use_env_proxy=use_env_proxy,
            once=once,
            show_local=show_local,
        )
    )
