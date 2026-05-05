from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import time
from collections.abc import Iterable

from meshping.agent.reporter import send_report
from meshping.config.settings import Settings
from meshping.models.node import Node
from meshping.prober.agent_probe import probe_agent
from meshping.protocol.packet import (
    decode_control_message,
    decode_probe_packet,
    decode_discovery_response,
    encode_control_message,
    encode_discovery_request,
    encode_discovery_response,
    encode_probe_reply,
)


class MeshpingAgent:
    def __init__(
        self,
        *,
        local_node: Node,
        settings: Settings,
        peers: list[Node] | None = None,
        coordinator: tuple[str, int] | None = None,
    ) -> None:
        self.local_node = local_node
        self.settings = settings
        self.peers = peers or []
        self.coordinator = coordinator
        self.sequence = 1
        self.transport: asyncio.DatagramTransport | None = None
        self._probe_task: asyncio.Task[None] | None = None
        self._running = asyncio.Event()

    def configure(
        self,
        *,
        peers: list[Node] | None = None,
        coordinator: tuple[str, int] | None = None,
        interval: float | None = None,
        timeout: float | None = None,
    ) -> None:
        if peers is not None:
            self.peers = peers
        if coordinator is not None:
            self.coordinator = coordinator
        if interval is not None:
            self.settings.probe_interval_s = interval
        if timeout is not None:
            self.settings.probe_timeout_s = timeout
        self._ensure_probe_task()

    def _ensure_probe_task(self) -> None:
        if self.coordinator and self.peers and (
            self._probe_task is None or self._probe_task.done()
        ):
            self._probe_task = asyncio.create_task(self._probe_loop())

    async def run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        self._running.set()
        self._ensure_probe_task()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _AgentProtocol(self),
            local_addr=(self.local_node.host, self.local_node.port),
        )
        self.transport = transport
        try:
            await asyncio.Future()
        finally:
            await self.stop()

    async def stop(self) -> None:
        self._running.clear()
        if self._probe_task:
            self._probe_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._probe_task
        if self.transport:
            self.transport.close()

    async def _probe_loop(self) -> None:
        while self._running.is_set():
            if not self.coordinator:
                await asyncio.sleep(self.settings.probe_interval_s)
                continue

            tasks = [
                probe_agent(
                    peer,
                    source_id=self.local_node.id,
                    timeout=self.settings.probe_timeout_s,
                    sequence=self._next_sequence(),
                    node_id_hash=self.local_node.short_id_hash,
                )
                for peer in self.peers
                if peer.id != self.local_node.id
            ]
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, Exception):
                        continue
                    await send_report(
                        result,
                        coordinator_host=self.coordinator[0],
                        coordinator_port=self.coordinator[1],
                    )
            await asyncio.sleep(self.settings.probe_interval_s)

    def _next_sequence(self) -> int:
        current = self.sequence
        self.sequence += 1
        return current


class _AgentProtocol(asyncio.DatagramProtocol):
    def __init__(self, agent: MeshpingAgent) -> None:
        self.agent = agent
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if data == encode_discovery_request():
            if self.transport:
                self.transport.sendto(encode_discovery_response(self.agent.local_node), addr)
            return

        if data.startswith(b"MSHC"):
            try:
                payload = decode_control_message(data)
            except ValueError:
                return
            peers = [
                Node.model_validate(node_payload | {"agent": True})
                for node_payload in payload.get("peers", [])
            ]
            coordinator_host = payload.get("coordinator_host")
            coordinator_port = payload.get("coordinator_port")
            coordinator = None
            if coordinator_host and coordinator_port:
                coordinator = (coordinator_host, int(coordinator_port))
            self.agent.configure(
                peers=peers,
                coordinator=coordinator,
                interval=payload.get("probe_interval_s"),
                timeout=payload.get("probe_timeout_s"),
            )
            if self.transport:
                self.transport.sendto(b"OK", addr)
            return

        try:
            packet = decode_probe_packet(data)
        except ValueError:
            return
        if self.transport:
            self.transport.sendto(
                encode_probe_reply(packet, time.time_ns()),
                addr,
            )


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.discovered: dict[str, Node] = {}

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            node = decode_discovery_response(data)
        except ValueError:
            return
        if not node.host or node.host in {"0.0.0.0", "::"}:
            node.host = addr[0]
        node.resolved_ip = addr[0]
        self.discovered[node.id] = node


async def push_agent_configuration(
    agents: Iterable[Node],
    *,
    coordinator_host: str,
    coordinator_port: int,
    settings: Settings,
) -> None:
    nodes_payload = [node.model_dump(mode="json") for node in agents]
    loop = asyncio.get_running_loop()

    for agent in agents:
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            remote_addr=(agent.resolved_ip or agent.host, agent.port),
        )
        try:
            payload = encode_control_message(
                {
                    "peers": nodes_payload,
                    "coordinator_host": coordinator_host,
                    "coordinator_port": coordinator_port,
                    "probe_interval_s": settings.probe_interval_s,
                    "probe_timeout_s": settings.probe_timeout_s,
                }
            )
            transport.sendto(payload)
            await asyncio.sleep(0)
        finally:
            transport.close()


async def discover_agents(
    subnet: str, *, port: int, timeout: float = 2.0
) -> list[Node]:
    network = ipaddress.ip_network(subnet, strict=False)
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        _DiscoveryProtocol,
        local_addr=("0.0.0.0", 0),
    )
    assert isinstance(protocol, _DiscoveryProtocol)
    try:
        request = encode_discovery_request()
        for host in network.hosts():
            transport.sendto(request, (str(host), port))
        await asyncio.sleep(timeout)
        return sorted(protocol.discovered.values(), key=lambda node: node.name or node.id)
    finally:
        transport.close()
