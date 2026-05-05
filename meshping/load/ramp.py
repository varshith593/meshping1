from __future__ import annotations

from meshping.load.sustained import run_sustained
from meshping.models.node import Node
from meshping.models.stress_result import StressResult, StressStatus

DEFAULT_RAMP_STEPS = [10, 25, 50, 100, 200, 300, 500, 1000]


async def run_ramp(
    target: Node | str,
    *,
    steps: list[int] | None = None,
    step_duration_s: float = 10.0,
    protocol: str = "tcp",
    timeout: float = 2.0,
) -> list[StressResult]:
    results: list[StressResult] = []
    baseline_p99: float | None = None
    baseline_p50: float | None = None
    breaking_streak = 0
    for rate in steps or DEFAULT_RAMP_STEPS:
        result = await run_sustained(
            target,
            rate=rate,
            duration_s=step_duration_s,
            protocol=protocol,
            timeout=timeout,
            baseline_p99=baseline_p99,
            baseline_p50=baseline_p50,
        )
        if baseline_p99 is None and result.p99_rtt is not None:
            baseline_p99 = result.p99_rtt
        if baseline_p50 is None and result.p50_rtt is not None:
            baseline_p50 = result.p50_rtt
        results.append(result)
        if result.status == StressStatus.BREAKING:
            breaking_streak += 1
            if breaking_streak >= 2:
                break
        else:
            breaking_streak = 0
    return results
