from __future__ import annotations

import asyncio
import time

from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult, ProbeType
from meshping.protocol.packet import decode_probe_reply, encode_probe_packet


class _UDPProbeProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.transport: asyncio.DatagramTransport | None = None
        self.future: asyncio.Future[bytes] | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if self.future and not self.future.done():
            self.future.set_result(data)

    def error_received(self, exc: Exception) -> None:
        if self.future and not self.future.done():
            self.future.set_exception(exc)


async def probe_udp_agent(
    target: Node,
    *,
    source_id: str,
    timeout: float,
    sequence: int,
    node_id_hash: int,
    payload: bytes | None = None,
) -> ProbeResult:
    loop = asyncio.get_running_loop()
    protocol = _UDPProbeProtocol()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: protocol,
        remote_addr=(target.resolved_ip or target.host, target.port),
    )
    sent_at = time.time_ns()
    packet = payload or encode_probe_packet(sequence, sent_at, node_id_hash)
    protocol.future = loop.create_future()
    try:
        transport.sendto(packet)
        data = await asyncio.wait_for(protocol.future, timeout=timeout)
        received_at = time.time_ns()
        try:
            reply = decode_probe_reply(data)
            remote_received_at = reply.receive_timestamp_ns
        except ValueError:
            remote_received_at = None
        return ProbeResult(
            source_id=source_id,
            target_id=target.id,
            sequence=sequence,
            sent_at=sent_at,
            received_at=received_at,
            remote_received_at=remote_received_at,
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
