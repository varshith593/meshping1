from __future__ import annotations

import math
import statistics
from collections.abc import Iterable

from meshping.models.probe_result import ProbeResult
from meshping.models.stress_result import StressResult, StressStatus


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    if pct == 0.5:
        return float(statistics.median(values))
    ordered = sorted(values)
    index = min(max(math.ceil(len(ordered) * pct) - 1, 0), len(ordered) - 1)
    return ordered[index]


def summarize_results(
    results: Iterable[ProbeResult],
    *,
    load_level_pps: int,
    baseline_p99: float | None = None,
    baseline_p50: float | None = None,
    duration_s: float | None = None,
    protocol: str = "tcp",
    target: str | None = None,
) -> StressResult:
    result_list = list(results)
    valid = [result.rtt_ms for result in result_list if result.success and result.rtt_ms is not None]
    attempted = len(result_list)
    succeeded = len(valid)
    refused = sum(1 for result in result_list if result.error == "connection_refused")
    timed_out = sum(1 for result in result_list if result.error == "timeout")
    loss_pct = ((attempted - succeeded) / attempted * 100) if attempted else 0.0
    avg = statistics.fmean(valid) if valid else None
    p50 = percentile(valid, 0.5)
    p99 = percentile(valid, 0.99)
    max_rtt = max(valid) if valid else None
    achieved_pps = attempted / duration_s if duration_s and duration_s > 0 else None
    degradation_pct = (
        ((p50 - baseline_p50) / baseline_p50) * 100
        if p50 is not None and baseline_p50 and baseline_p50 > 0
        else None
    )
    status = classify_stress(p99=p99, loss_pct=loss_pct, baseline_p99=baseline_p99)
    return StressResult(
        load_level_pps=load_level_pps,
        requested_pps=load_level_pps,
        achieved_pps=achieved_pps,
        degradation_pct=degradation_pct,
        avg_rtt=avg,
        p50_rtt=p50,
        p99_rtt=p99,
        loss_pct=loss_pct,
        status=status,
        attempted=attempted,
        succeeded=succeeded,
        refused=refused,
        timed_out=timed_out,
        max_rtt=max_rtt,
        protocol=protocol,
        target=target,
    )


def classify_stress(
    *,
    p99: float | None,
    loss_pct: float,
    baseline_p99: float | None,
) -> StressStatus:
    baseline = baseline_p99 or p99 or 1.0
    if loss_pct > 5.0 or (p99 is not None and p99 > baseline * 5):
        return StressStatus.BREAKING
    if loss_pct >= 1.0 or (p99 is not None and p99 >= baseline * 3):
        return StressStatus.DEGRADING
    return StressStatus.HEALTHY


def sparkline(values: Iterable[float | None]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    clean = [value for value in values if value is not None]
    if not clean:
        return ""
    low = min(clean)
    high = max(clean)
    if high == low:
        return blocks[0] * len(clean)
    return "".join(
        blocks[min(int((value - low) / (high - low) * (len(blocks) - 1)), len(blocks) - 1)]
        for value in clean
    )
