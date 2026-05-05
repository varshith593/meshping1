from __future__ import annotations

import asyncio

from meshping.models.probe_result import ProbeResult
from meshping.protocol.packet import encode_result_report


async def send_report(
    result: ProbeResult, *, coordinator_host: str, coordinator_port: int
) -> None:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        asyncio.DatagramProtocol,
        remote_addr=(coordinator_host, coordinator_port),
    )
    try:
        transport.sendto(encode_result_report(result))
        await asyncio.sleep(0)
    finally:
        transport.close()
