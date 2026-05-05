from __future__ import annotations

import asyncio

import click
from rich.console import Console

from meshping.load.sustained import run_sustained
from meshping.prober.http import aiohttp
from meshping.ui.stress_view import render_stress_table

from ._common import parse_duration


@click.command("canary")
@click.argument("url")
@click.option("--rate", default=100, show_default=True, type=int)
@click.option("--duration", default="30s", show_default=True)
@click.option("--timeout", default=2.0, show_default=True, type=float)
def canary_command(url: str, rate: int, duration: str, timeout: float) -> None:
    """Run HTTP GET canary load against a backend URL."""
    if aiohttp is None:
        raise click.ClickException("aiohttp is not installed; run pip install -e .")
    result = asyncio.run(
        _run_canary(
            url,
            rate=rate,
            duration_s=parse_duration(duration),
            timeout=timeout,
        )
    )
    Console().print(render_stress_table([result]))


async def _run_canary(url: str, *, rate: int, duration_s: float, timeout: float):
    connector = aiohttp.TCPConnector(limit=min(rate, 100))
    async with aiohttp.ClientSession(connector=connector) as session:
        return await run_sustained(
            url,
            rate=rate,
            duration_s=duration_s,
            protocol="http",
            timeout=timeout,
            session=session,
        )
