from __future__ import annotations

import asyncio
import itertools
import time

from meshping.load.protocol_load import probe_by_protocol
from meshping.load.stats import summarize_results
from meshping.local.nic import NICWatcher, default_interface, sample_deltas
from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult
from meshping.models.stress_result import StressResult


async def run_sustained(
    target: Node | str,
    *,
    rate: int,
    duration_s: float,
    protocol: str = "tcp",
    timeout: float = 2.0,
    source_id: str = "local",
    session: object | None = None,
    baseline_p99: float | None = None,
    baseline_p50: float | None = None,
) -> StressResult:
    watcher: NICWatcher | None = None
    sampler_task: asyncio.Task[None] | None = None
    interface = default_interface()
    if interface:
        watcher = NICWatcher(interface=interface)
        sampler_task = asyncio.create_task(_sample_nic(watcher, duration_s))
    results = await collect_sustained(
        target,
        rate=rate,
        duration_s=duration_s,
        protocol=protocol,
        timeout=timeout,
        source_id=source_id,
        session=session,
    )
    if sampler_task:
        await sampler_task
    summary = summarize_results(
        results,
        load_level_pps=rate,
        baseline_p99=baseline_p99,
        baseline_p50=baseline_p50,
        duration_s=duration_s,
        protocol=protocol,
        target=target if isinstance(target, str) else f"{target.host}:{target.port}",
    )
    if watcher:
        deltas = sample_deltas(watcher.samples)
        if any(delta.tx_dropped_per_sec > 0 for delta in deltas):
            summary.nic_saturated_at = rate
            summary.note = f"Local NIC reported TX drops while testing {rate} pkt/s."
    return summary


async def collect_sustained(
    target: Node | str,
    *,
    rate: int,
    duration_s: float,
    protocol: str = "tcp",
    timeout: float = 2.0,
    source_id: str = "local",
    session: object | None = None,
) -> list[ProbeResult]:
    if rate <= 0:
        raise ValueError("rate must be greater than zero")
    if duration_s <= 0:
        raise ValueError("duration must be greater than zero")

    interval = 1.0 / rate
    started = time.monotonic()
    deadline = started + duration_s
    sequence = itertools.count(1)
    tasks: list[asyncio.Task[ProbeResult]] = []
    next_send = started

    while time.monotonic() < deadline:
        tasks.append(
            asyncio.create_task(
                probe_by_protocol(
                    target,
                    protocol=protocol,
                    source_id=source_id,
                    timeout=timeout,
                    sequence=next(sequence),
                    session=session,
                )
            )
        )
        next_send += interval
        await asyncio.sleep(max(0.0, next_send - time.monotonic()))

    if not tasks:
        return []
    return list(await asyncio.gather(*tasks))


async def _sample_nic(watcher: NICWatcher, duration_s: float) -> None:
    deadline = time.monotonic() + duration_s
    while time.monotonic() <= deadline:
        watcher.sample()
        await asyncio.sleep(1.0)
