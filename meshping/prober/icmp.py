from __future__ import annotations

import asyncio
import platform
import re
import time

from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult, ProbeType

PING_RTT_PATTERN = re.compile(r"time[=<]([0-9.]+)\s*ms")


async def probe_icmp(
    target: Node, *, source_id: str, timeout: float, sequence: int
) -> ProbeResult:
    sent_at = time.time_ns()
    timeout_ms = max(int(timeout * 1000), 1)
    system = platform.system().lower()
    if system == "darwin":
        args = ["ping", "-c", "1", "-W", str(timeout_ms), target.host]
    else:
        args = ["ping", "-c", "1", "-W", str(max(int(timeout), 1)), target.host]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    received_at = time.time_ns()
    output = (stdout + stderr).decode("utf-8", errors="ignore")

    if proc.returncode == 0:
        match = PING_RTT_PATTERN.search(output)
        rtt_ms = float(match.group(1)) if match else (received_at - sent_at) / 1_000_000
        return ProbeResult(
            source_id=source_id,
            target_id=target.id,
            sequence=sequence,
            sent_at=sent_at,
            received_at=received_at,
            rtt_ms=rtt_ms,
            success=True,
            error=None,
            probe_type=ProbeType.ICMP,
        )

    error = "timeout" if "100.0% packet loss" in output else "icmp_failed"
    return ProbeResult(
        source_id=source_id,
        target_id=target.id,
        sequence=sequence,
        sent_at=sent_at,
        received_at=received_at,
        rtt_ms=None,
        success=False,
        error=error,
        probe_type=ProbeType.ICMP,
    )
