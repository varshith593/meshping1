from __future__ import annotations

import asyncio
import time

from meshping.models.probe_result import ProbeResult, ProbeType

try:
    import aiohttp
except ImportError:  # pragma: no cover
    aiohttp = None


async def probe_http(
    url: str,
    *,
    session: object | None = None,
    timeout: float = 2.0,
    source_id: str = "local",
    target_id: str | None = None,
    sequence: int = 1,
) -> ProbeResult:
    if aiohttp is None:
        now = time.time_ns()
        return ProbeResult(
            source_id=source_id,
            target_id=target_id or url,
            sequence=sequence,
            sent_at=now,
            received_at=now,
            rtt_ms=None,
            success=False,
            error="aiohttp_not_installed",
            probe_type=ProbeType.HTTP,
        )

    sent_at = time.time_ns()
    owns_session = session is None
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    client = session or aiohttp.ClientSession(timeout=client_timeout)
    try:
        async with client.get(url, timeout=client_timeout) as resp:
            await resp.content.read(1)
            received_at = time.time_ns()
            success = resp.status < 500
            return ProbeResult(
                source_id=source_id,
                target_id=target_id or url,
                sequence=sequence,
                sent_at=sent_at,
                received_at=received_at,
                rtt_ms=(received_at - sent_at) / 1_000_000,
                success=success,
                error=None if success else f"HTTP {resp.status}",
                probe_type=ProbeType.HTTP,
            )
    except asyncio.TimeoutError:
        return ProbeResult(
            source_id=source_id,
            target_id=target_id or url,
            sequence=sequence,
            sent_at=sent_at,
            received_at=None,
            rtt_ms=None,
            success=False,
            error="timeout",
            probe_type=ProbeType.HTTP,
        )
    except Exception as exc:
        received_at = time.time_ns()
        return ProbeResult(
            source_id=source_id,
            target_id=target_id or url,
            sequence=sequence,
            sent_at=sent_at,
            received_at=received_at,
            rtt_ms=None,
            success=False,
            error=exc.__class__.__name__.lower(),
            probe_type=ProbeType.HTTP,
        )
    finally:
        if owns_session:
            await client.close()
