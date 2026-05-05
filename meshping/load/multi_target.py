from __future__ import annotations

import asyncio

from meshping.load.sustained import run_sustained
from meshping.models.node import Node
from meshping.models.stress_result import StressResult


async def run_multi_target(
    distribution: list[tuple[Node, float]],
    *,
    total_rate: int,
    duration_s: float,
    protocol: str = "tcp",
    timeout: float = 2.0,
) -> list[StressResult]:
    if total_rate <= 0:
        raise ValueError("total_rate must be greater than zero")
    tasks = []
    for node, percent in distribution:
        rate = max(1, round(total_rate * (percent / 100.0)))
        tasks.append(
            run_sustained(
                node,
                rate=rate,
                duration_s=duration_s,
                protocol=protocol,
                timeout=timeout,
            )
        )
    return list(await asyncio.gather(*tasks))
