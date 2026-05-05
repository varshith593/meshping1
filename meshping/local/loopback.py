from __future__ import annotations

import asyncio

from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult
from meshping.prober.tcp import probe_tcp


async def probe_loopback(
    *,
    timeout: float = 1.0,
    sequence: int = 1,
    source_id: str = "local",
) -> ProbeResult:
    async def handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        node = Node(id="localhost", host="127.0.0.1", port=port, name="localhost")
        return await probe_tcp(
            node,
            source_id=source_id,
            timeout=timeout,
            sequence=sequence,
            use_env_proxy=False,
        )
    finally:
        server.close()
        await server.wait_closed()
