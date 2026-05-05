from __future__ import annotations

import asyncio

import click

from meshping.agent.server import MeshpingAgent
from meshping.config.settings import Settings
from meshping.models.node import Node

from ._common import parse_nodes_argument, parse_listen


@click.command("agent")
@click.option("--name", required=True, help="Display name for this agent.")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=7777, show_default=True, type=int)
@click.option("--peers", help="Comma-separated agent list, e.g. web1=10.0.0.11:7777")
@click.option("--coordinator", help="Coordinator host:port for sending reports.")
@click.option("--interval", default=1.0, show_default=True, type=float)
@click.option("--timeout", default=2.0, show_default=True, type=float)
def agent_command(
    name: str,
    host: str,
    port: int,
    peers: str | None,
    coordinator: str | None,
    interval: float,
    timeout: float,
) -> None:
    """Run a meshping UDP agent."""
    settings = Settings(probe_interval_s=interval, probe_timeout_s=timeout, agent_port=port)
    coordinator_addr = parse_listen(coordinator) if coordinator else None
    local_node = Node(id=name, name=name, host=host, port=port, agent=True)
    peer_nodes = parse_nodes_argument(peers, agent=True)
    asyncio.run(
        MeshpingAgent(
            local_node=local_node,
            settings=settings,
            peers=peer_nodes,
            coordinator=coordinator_addr,
        ).run_forever()
    )
