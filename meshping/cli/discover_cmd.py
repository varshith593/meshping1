from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.table import Table

from meshping.agent.server import discover_agents


@click.command("discover")
@click.option("--subnet", required=True, help="CIDR subnet to scan, e.g. 192.168.1.0/24")
@click.option("--port", default=7777, show_default=True, type=int)
@click.option("--timeout", default=2.0, show_default=True, type=float)
def discover_command(subnet: str, port: int, timeout: float) -> None:
    """Discover meshping agents on a subnet."""
    agents = asyncio.run(discover_agents(subnet, port=port, timeout=timeout))
    console = Console()
    table = Table(title=f"Discovered agents on {subnet}")
    table.add_column("Name")
    table.add_column("Host")
    table.add_column("Port", justify="right")
    for node in agents:
        table.add_row(node.display_name, node.resolved_ip or node.host, str(node.port))
    console.print(table)
