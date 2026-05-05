from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.table import Table

from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult
from meshping.prober.agent_probe import probe_agent
from meshping.prober.icmp import probe_icmp
from meshping.prober.tcp import probe_tcp

from ._common import combine_target_inputs


@click.command("probe")
@click.argument("targets", nargs=-1)
@click.option("--nodes", help="Comma-separated list of host:port targets.")
@click.option("--timeout", default=2.0, show_default=True, type=float)
@click.option("--agent", "agent_mode", is_flag=True, help="Use UDP agent probing.")
@click.option("--icmp", is_flag=True, help="Use ICMP probing instead of TCP.")
@click.option("--proxy", help="HTTP CONNECT proxy URL for TCP probing.")
@click.option(
    "--no-proxy",
    is_flag=True,
    help="Disable proxy auto-detection from HTTP_PROXY/HTTPS_PROXY.",
)
def probe_command(
    targets: tuple[str, ...],
    nodes: str | None,
    timeout: float,
    agent_mode: bool,
    icmp: bool,
    proxy: str | None,
    no_proxy: bool,
) -> None:
    """Probe one or more targets once."""
    target_nodes = combine_target_inputs(targets, nodes, agent=agent_mode)
    if not target_nodes:
        raise click.UsageError("Provide at least one target or --nodes")
    results = asyncio.run(
        _probe_many(
            target_nodes,
            timeout=timeout,
            agent_mode=agent_mode,
            icmp=icmp,
            proxy_url=proxy,
            use_env_proxy=not no_proxy,
        )
    )

    console = Console()
    table = Table(title="meshping probe")
    table.add_column("Target")
    table.add_column("Type")
    table.add_column("Result", justify="right")
    table.add_column("Status")
    for node, result in zip(target_nodes, results, strict=False):
        status = "ok" if result.success else result.error or "failed"
        metric = f"{result.rtt_ms:.2f}ms" if result.rtt_ms is not None else "-"
        table.add_row(f"{node.host}:{node.port}", result.probe_type, metric, status)
    console.print(table)


async def _probe_many(
    nodes: list[Node],
    *,
    timeout: float,
    agent_mode: bool,
    icmp: bool,
    proxy_url: str | None = None,
    use_env_proxy: bool = True,
) -> list[ProbeResult]:
    source = Node(id="local", host="localhost", port=1, name="local")
    tasks = []
    for sequence, node in enumerate(nodes, start=1):
        if icmp:
            tasks.append(
                probe_icmp(node, source_id=source.id, timeout=timeout, sequence=sequence)
            )
        elif agent_mode:
            tasks.append(
                probe_agent(
                    node,
                    source_id=source.id,
                    timeout=timeout,
                    sequence=sequence,
                    node_id_hash=source.short_id_hash,
                )
            )
        else:
            tasks.append(
                probe_tcp(
                    node,
                    source_id=source.id,
                    timeout=timeout,
                    sequence=sequence,
                    proxy_url=proxy_url,
                    use_env_proxy=use_env_proxy,
                )
            )
    return list(await asyncio.gather(*tasks))
