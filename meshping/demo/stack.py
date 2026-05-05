from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import time
from dataclasses import dataclass

from rich.table import Table

from meshping.agent.reporter import send_report
from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult, ProbeType


DEMO_COORDINATOR = "127.0.0.1:17880"


@dataclass(frozen=True)
class DemoServiceSpec:
    name: str
    http_port: int
    agent_port: int
    tier: str
    base_ms: float
    summary: str


_DEMO_SPECS: tuple[DemoServiceSpec, ...] = (
    DemoServiceSpec("frontend", 18080, 17770, "edge", 0.8, "Public web entrypoint"),
    DemoServiceSpec("backend", 18081, 17771, "edge", 1.1, "Main API service"),
    DemoServiceSpec("auth", 18082, 17772, "edge", 1.3, "Login and token service"),
    DemoServiceSpec("orders", 18083, 17773, "core", 1.9, "Order workflow service"),
    DemoServiceSpec("payments", 18084, 17774, "core", 2.4, "Payment orchestration"),
    DemoServiceSpec("inventory", 18085, 17775, "core", 1.7, "Inventory read/write service"),
    DemoServiceSpec("redis", 18086, 17776, "data", 0.9, "Fast cache tier"),
    DemoServiceSpec("postgres", 18087, 17777, "data", 3.2, "Primary relational database"),
)

_TIER_LATENCY_MS: dict[frozenset[str], float] = {
    frozenset({"edge"}): 0.9,
    frozenset({"core"}): 1.4,
    frozenset({"data"}): 1.0,
    frozenset({"edge", "core"}): 4.8,
    frozenset({"core", "data"}): 5.6,
    frozenset({"edge", "data"}): 8.2,
}


def demo_specs() -> list[DemoServiceSpec]:
    return list(_DEMO_SPECS)


def demo_service_nodes(host: str = "127.0.0.1") -> list[Node]:
    return [
        Node(id=spec.name, name=spec.name, host=host, port=spec.http_port)
        for spec in _DEMO_SPECS
    ]


def demo_agent_nodes(host: str = "127.0.0.1") -> list[Node]:
    return [
        Node(
            id=spec.name,
            name=spec.name,
            host=host,
            port=spec.agent_port,
            agent=True,
        )
        for spec in _DEMO_SPECS
    ]


def render_demo_table(host: str = "127.0.0.1") -> Table:
    table = Table(title="Demo Microservices", expand=True)
    table.add_column("Service")
    table.add_column("HTTP", justify="right")
    table.add_column("Matrix ID")
    table.add_column("Tier")
    table.add_column("Purpose")
    for spec in _DEMO_SPECS:
        table.add_row(
            spec.name,
            f"{host}:{spec.http_port}",
            spec.name,
            spec.tier,
            spec.summary,
        )
    return table


def synthetic_latency_ms(source_id: str, target_id: str, tick: int) -> float:
    if source_id == target_id:
        return 0.0

    left = _spec_by_name(source_id)
    right = _spec_by_name(target_id)
    tier_base = _TIER_LATENCY_MS[frozenset({left.tier, right.tier})]
    service_bias = (left.base_ms + right.base_ms) / 5.0
    index_gap = abs(_service_index(left.name) - _service_index(right.name)) * 0.22
    phase = _pair_phase(left.name, right.name)
    wave = 0.18 * math.sin((tick / 2.0) + phase)
    return round(max(0.35, tier_base + service_bias + index_gap + wave), 2)


class DemoStack:
    def __init__(
        self,
        *,
        host: str,
        coordinator_host: str,
        coordinator_port: int,
        interval_s: float = 1.0,
    ) -> None:
        self.host = host
        self.coordinator_host = coordinator_host
        self.coordinator_port = coordinator_port
        self.interval_s = interval_s
        self._servers: list[asyncio.AbstractServer] = []
        self._report_task: asyncio.Task[None] | None = None
        self._running = asyncio.Event()
        self._sequence = 1

    async def run_forever(self) -> None:
        self._running.set()
        await self._start_http_services()
        self._report_task = asyncio.create_task(self._report_loop())
        try:
            await asyncio.Future()
        finally:
            await self.stop()

    async def stop(self) -> None:
        self._running.clear()
        if self._report_task:
            self._report_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._report_task
        for server in self._servers:
            server.close()
            await server.wait_closed()
        self._servers.clear()

    async def _start_http_services(self) -> None:
        for spec in _DEMO_SPECS:
            server = await asyncio.start_server(
                lambda reader, writer, service=spec: self._handle_http(service, reader, writer),
                host=self.host,
                port=spec.http_port,
            )
            self._servers.append(server)

    async def _handle_http(
        self,
        spec: DemoServiceSpec,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        with contextlib.suppress(Exception):
            await reader.readuntil(b"\r\n\r\n")
        await asyncio.sleep(spec.base_ms / 1000.0)
        payload = {
            "service": spec.name,
            "tier": spec.tier,
            "status": "ok",
            "summary": spec.summary,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = [
            "HTTP/1.1 200 OK",
            "Content-Type: application/json",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "",
            "",
        ]
        writer.write("\r\n".join(headers).encode("utf-8") + body)
        with contextlib.suppress(Exception):
            await writer.drain()
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()

    async def _report_loop(self) -> None:
        tick = 0
        names = [spec.name for spec in _DEMO_SPECS]
        while self._running.is_set():
            for source_id in names:
                for target_id in names:
                    if source_id == target_id:
                        continue
                    rtt_ms = synthetic_latency_ms(source_id, target_id, tick)
                    sent_at = time.time_ns()
                    received_at = sent_at + int(rtt_ms * 1_000_000)
                    result = ProbeResult(
                        source_id=source_id,
                        target_id=target_id,
                        sequence=self._next_sequence(),
                        sent_at=sent_at,
                        received_at=received_at,
                        remote_received_at=sent_at + int((rtt_ms / 2.0) * 1_000_000),
                        rtt_ms=rtt_ms,
                        success=True,
                        probe_type=ProbeType.UDP,
                    )
                    await send_report(
                        result,
                        coordinator_host=self.coordinator_host,
                        coordinator_port=self.coordinator_port,
                    )
            tick += 1
            await asyncio.sleep(self.interval_s)

    def _next_sequence(self) -> int:
        sequence = self._sequence
        self._sequence += 1
        return sequence


def _spec_by_name(name: str) -> DemoServiceSpec:
    for spec in _DEMO_SPECS:
        if spec.name == name:
            return spec
    raise KeyError(name)


def _service_index(name: str) -> int:
    for index, spec in enumerate(_DEMO_SPECS):
        if spec.name == name:
            return index
    raise KeyError(name)


def _pair_phase(left: str, right: str) -> float:
    pair = ":".join(sorted((left, right))).encode("utf-8")
    digest = hashlib.blake2b(pair, digest_size=2).digest()
    return int.from_bytes(digest, "big") / 65535 * math.pi
