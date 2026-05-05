from __future__ import annotations

import click

from meshping.config.settings import Settings

from ._common import combine_target_inputs
from .mesh_cmd import run_mesh_session


@click.command("top")
@click.argument("targets", nargs=-1)
@click.option("--nodes", help="Comma-separated TCP targets.")
@click.option("--interval", default=1.0, show_default=True, type=float)
@click.option("--timeout", default=2.0, show_default=True, type=float)
@click.option("--history-window", default=100, show_default=True, type=int)
@click.option("--profile", default="work", show_default=True, type=click.Choice(["work", "gaming", "video"]))
@click.option("--proxy", help="HTTP CONNECT proxy URL for TCP probing.")
@click.option(
    "--no-proxy",
    is_flag=True,
    help="Disable proxy auto-detection from HTTP_PROXY/HTTPS_PROXY.",
)
def top_command(
    targets: tuple[str, ...],
    nodes: str | None,
    interval: float,
    timeout: float,
    history_window: int,
    profile: str,
    proxy: str | None,
    no_proxy: bool,
) -> None:
    """Show live latency with local CPU/RAM correlation."""
    target_nodes = combine_target_inputs(
        targets,
        nodes,
        use_sandbox_defaults=True,
    )
    settings = Settings(
        probe_interval_s=interval,
        probe_timeout_s=timeout,
        history_window=history_window,
        usage_profile=profile,
    )
    run_mesh_session(
        target_nodes,
        settings=settings,
        proxy_url=proxy,
        use_env_proxy=not no_proxy,
        show_local=True,
    )
