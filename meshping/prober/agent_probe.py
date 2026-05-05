from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult, ProbeType
from meshping.protocol.packet import (
    decode_probe_reply,
    encode_probe_packet,
)


class _AgentProbeProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        *,
        payload: bytes,
        future: asyncio.Future[bytes],
        on_send: Callable[[asyncio.DatagramTransport], None],
    ) -> None:
        self.payload = payload
        self.future = future
        self.on_send = on_send
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]
        self.on_send(self.transport)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not self.future.done():
            self.future.set_result(data)
        if self.transport:
            self.transport.close()

    def error_received(self, exc: Exception) -> None:
        if not self.future.done():
            self.future.set_exception(exc)
        if self.transport:
            self.transport.close()


async def probe_agent(
    target: Node,
    *,
    source_id: str,
    timeout: float,
    sequence: int,
    node_id_hash: int,
) -> ProbeResult:
    loop = asyncio.get_running_loop()
    sent_at = time.time_ns()
    payload = encode_probe_packet(sequence, sent_at, node_id_hash)
    future: asyncio.Future[bytes] = loop.create_future()

    def send_probe(transport: asyncio.DatagramTransport) -> None:
        transport.sendto(payload, (target.resolved_ip or target.host, target.port))

    transport, _ = await loop.create_datagram_endpoint(
        lambda: _AgentProbeProtocol(payload=payload, future=future, on_send=send_probe),
        local_addr=("0.0.0.0", 0),
    )
    try:
        response = await asyncio.wait_for(future, timeout=timeout)
        received_at = time.time_ns()
        reply = decode_probe_reply(response)
        if reply.sequence != sequence or reply.node_id_hash != node_id_hash:
            raise ValueError("reply did not match the active probe")
        return ProbeResult(
            source_id=source_id,
            target_id=target.id,
            sequence=sequence,
            sent_at=sent_at,
            received_at=received_at,
            remote_received_at=reply.receive_timestamp_ns,
            rtt_ms=(received_at - sent_at) / 1_000_000,
            success=True,
            error=None,
            probe_type=ProbeType.UDP,
        )
    except asyncio.TimeoutError:
        return ProbeResult(
            source_id=source_id,
            target_id=target.id,
            sequence=sequence,
            sent_at=sent_at,
            received_at=None,
            rtt_ms=None,
            success=False,
            error="timeout",
            probe_type=ProbeType.UDP,
        )
    except ValueError as exc:
        received_at = time.time_ns()
        return ProbeResult(
            source_id=source_id,
            target_id=target.id,
            sequence=sequence,
            sent_at=sent_at,
            received_at=received_at,
            rtt_ms=None,
            success=False,
            error=f"invalid_reply: {exc}",
            probe_type=ProbeType.UDP,
        )
    except OSError as exc:
        received_at = time.time_ns()
        return ProbeResult(
            source_id=source_id,
            target_id=target.id,
            sequence=sequence,
            sent_at=sent_at,
            received_at=received_at,
            rtt_ms=None,
            success=False,
            error=exc.strerror or exc.__class__.__name__.lower(),
            probe_type=ProbeType.UDP,
        )
    finally:
        transport.close()
