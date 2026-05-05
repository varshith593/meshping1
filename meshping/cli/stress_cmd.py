from __future__ import annotations

import asyncio

import click
from rich.console import Console

from meshping.load.multi_target import run_multi_target
from meshping.load.pool_stress import run_pool_stress
from meshping.load.ramp import DEFAULT_RAMP_STEPS, run_ramp
from meshping.load.sustained import run_sustained
from meshping.models.node import Node
from meshping.ui.stress_view import (
    render_ramp_chart,
    render_ramp_result,
    render_stress_table,
)

from ._common import parse_duration, parse_levels, parse_load_distribution


@click.command("stress")
@click.argument("target", required=False)
@click.option("--rate", default=100, show_default=True, type=int)
@click.option("--duration", default="30s", show_default=True)
@click.option("--ramp", is_flag=True, help="Run graduated load ramp.")
@click.option("--step-duration", default="10s", show_default=True)
@click.option("--max-rate", type=int, help="Highest ramp rate to run.")
@click.option("--protocol", type=click.Choice(["tcp", "http", "udp"]), default="tcp", show_default=True)
@click.option("--load", "loads", multiple=True, help="Multi-target load item host:port=percent%.")
@click.option("--total-rate", default=100, show_default=True, type=int)
@click.option("--pool-test", is_flag=True, help="Run concurrent TCP connection pool test.")
@click.option("--levels", default="10,25,50,100", show_default=True)
@click.option("--timeout", default=2.0, show_default=True, type=float)
def stress_command(
    target: str | None,
    rate: int,
    duration: str,
    ramp: bool,
    step_duration: str,
    max_rate: int | None,
    protocol: str,
    loads: tuple[str, ...],
    total_rate: int,
    pool_test: bool,
    levels: str,
    timeout: float,
) -> None:
    """Run sustained, ramp, multi-target, or pool stress tests."""
    mode, results = asyncio.run(
        _run_stress(
            target=target,
            rate=rate,
            duration_s=parse_duration(duration),
            ramp=ramp,
            step_duration_s=parse_duration(step_duration),
            max_rate=max_rate,
            protocol=protocol,
            loads=loads,
            total_rate=total_rate,
            pool_test=pool_test,
            levels=parse_levels(levels),
            timeout=timeout,
        )
    )
    console = Console()
    if mode == "ramp":
        console.print(render_ramp_result(results))
        console.print(render_ramp_chart(results))
        return
    console.print(render_stress_table(results))


async def _run_stress(
    *,
    target: str | None,
    rate: int,
    duration_s: float,
    ramp: bool,
    step_duration_s: float,
    max_rate: int | None,
    protocol: str,
    loads: tuple[str, ...],
    total_rate: int,
    pool_test: bool,
    levels: list[int],
    timeout: float,
):
    if loads:
        return "multi", await run_multi_target(
            parse_load_distribution(loads),
            total_rate=total_rate,
            duration_s=duration_s,
            protocol=protocol,
            timeout=timeout,
        )
    if not target:
        raise click.UsageError("Provide a target or --load entries")
    node_or_url = target if protocol == "http" and target.startswith(("http://", "https://")) else Node.from_target(target)
    if pool_test:
        if isinstance(node_or_url, str):
            raise click.UsageError("--pool-test requires host:port")
        return "pool", await run_pool_stress(node_or_url, levels=levels, timeout=timeout)
    if ramp:
        steps = DEFAULT_RAMP_STEPS
        if max_rate:
            steps = [step for step in steps if step <= max_rate]
        return "ramp", await run_ramp(
            node_or_url,
            steps=steps,
            step_duration_s=step_duration_s,
            protocol=protocol,
            timeout=timeout,
        )
    result = await run_sustained(
        node_or_url,
        rate=rate,
        duration_s=duration_s,
        protocol=protocol,
        timeout=timeout,
    )
    return "sustained", [result]
