from __future__ import annotations

import asyncio
import time

from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult, ProbeType
from meshping.models.stress_result import StressResult, StressStatus


async def run_pool_stress(
    target: Node,
    *,
    levels: list[int],
    timeout: float = 2.0,
) -> list[StressResult]:
    results: list[StressResult] = []
    for level in levels:
        probes = await _open_many(target, level=level, timeout=timeout)
        succeeded = [probe for probe in probes if probe.success and probe.rtt_ms is not None]
        refused = sum(1 for probe in probes if probe.error == "connection_refused")
        timed_out = sum(1 for probe in probes if probe.error == "timeout")
        loss_pct = ((level - len(succeeded)) / level * 100) if level else 0.0
        status = StressStatus.HEALTHY
        if refused or timed_out or loss_pct > 5.0:
            status = StressStatus.BREAKING
        elif loss_pct > 0:
            status = StressStatus.DEGRADING
        rtts = [probe.rtt_ms for probe in succeeded if probe.rtt_ms is not None]
        results.append(
            StressResult(
                load_level_pps=level,
                avg_rtt=(sum(rtts) / len(rtts)) if rtts else None,
                p50_rtt=None,
                p99_rtt=None,
                loss_pct=loss_pct,
                status=status,
                attempted=level,
                succeeded=len(succeeded),
                refused=refused,
                timed_out=timed_out,
                max_rtt=max(rtts) if rtts else None,
                protocol="pool",
                target=f"{target.host}:{target.port}",
            )
        )
    return results


async def _open_many(target: Node, *, level: int, timeout: float) -> list[ProbeResult]:
    async def open_one(sequence: int) -> ProbeResult:
        sent_at = time.time_ns()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(target.host, target.port),
                timeout=timeout,
            )
            received_at = time.time_ns()
            writer.close()
            await writer.wait_closed()
            return ProbeResult(
                source_id="local",
                target_id=target.id,
                sequence=sequence,
                sent_at=sent_at,
                received_at=received_at,
                rtt_ms=(received_at - sent_at) / 1_000_000,
                success=True,
                error=None,
                probe_type=ProbeType.TCP,
            )
        except ConnectionRefusedError:
            received_at = time.time_ns()
            return ProbeResult(
                source_id="local",
                target_id=target.id,
                sequence=sequence,
                sent_at=sent_at,
                received_at=received_at,
                rtt_ms=None,
                success=False,
                error="connection_refused",
                probe_type=ProbeType.TCP,
            )
        except asyncio.TimeoutError:
            return ProbeResult(
                source_id="local",
                target_id=target.id,
                sequence=sequence,
                sent_at=sent_at,
                received_at=None,
                rtt_ms=None,
                success=False,
                error="timeout",
                probe_type=ProbeType.TCP,
            )
        except OSError as exc:
            received_at = time.time_ns()
            return ProbeResult(
                source_id="local",
                target_id=target.id,
                sequence=sequence,
                sent_at=sent_at,
                received_at=received_at,
                rtt_ms=None,
                success=False,
                error=exc.strerror or exc.__class__.__name__.lower(),
                probe_type=ProbeType.TCP,
            )

    return list(await asyncio.gather(*(open_one(seq) for seq in range(1, level + 1))))
