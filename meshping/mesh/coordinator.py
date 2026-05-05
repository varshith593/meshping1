from __future__ import annotations

import asyncio
import contextlib
import csv
import datetime as dt
import ipaddress
import itertools
import json
import socket
import time
from pathlib import Path
from typing import Any

import structlog

from meshping.agent.server import push_agent_configuration
from meshping.config.settings import Settings
from meshping.mesh.analyzer import Analyzer
from meshping.mesh.cluster import compute_clusters
from meshping.mesh.matrix import MatrixStore
from meshping.models.alert import Alert
from meshping.models.cluster import Cluster
from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult, ProbeType
from meshping.local.doctor import SplitBrainDiagnosis, diagnose_split_brain
from meshping.local.loopback import probe_loopback
from meshping.local.context import detect_network_context
from meshping.prober.agent_probe import probe_agent
from meshping.prober.fingerprint import fingerprint_service
from meshping.prober.tcp import probe_tcp
from meshping.protocol.packet import decode_result_report
from meshping.storage.recorder import ProbeRecorder

try:
    import aiodns
except ImportError:  # pragma: no cover
    aiodns = None

logger = structlog.get_logger(__name__)


def _prefer_result(left: ProbeResult, right: ProbeResult) -> ProbeResult:
    if left.success and right.success:
        if (left.rtt_ms or float("inf")) <= (right.rtt_ms or float("inf")):
            return left
        return right
    if left.success:
        return left
    if right.success:
        return right
    if left.error == "timeout" and right.error != "timeout":
        return right
    return left


class DNSResolver:
    def __init__(self, ttl_seconds: int) -> None:
        self.ttl_seconds = ttl_seconds
        self.cache: dict[str, tuple[float, dict[str, str]]] = {}
        self._resolver = None

    async def resolve(self, host: str) -> str:
        addresses = await self.resolve_all(host)
        if "IPv4" in addresses:
            return addresses["IPv4"]
        if "IPv6" in addresses:
            return addresses["IPv6"]
        return host

    async def resolve_all(self, host: str) -> dict[str, str]:
        try:
            parsed = ipaddress.ip_address(host)
            return {"IPv4" if parsed.version == 4 else "IPv6": host}
        except ValueError:
            pass

        now = time.monotonic()
        cached = self.cache.get(host)
        if cached and cached[0] > now:
            return cached[1]

        addresses: dict[str, str] = {}
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in infos:
            if family == socket.AF_INET and "IPv4" not in addresses:
                addresses["IPv4"] = sockaddr[0]
            elif family == socket.AF_INET6 and "IPv6" not in addresses:
                addresses["IPv6"] = sockaddr[0]
        if not addresses:
            addresses["IPv4"] = host
        self.cache[host] = (now + self.ttl_seconds, addresses)
        return addresses

    async def resolve_node(self, node: Node) -> Node:
        node.resolved_ip = await self.resolve(node.host)
        return node


class _ResultProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[ProbeResult]) -> None:
        self.queue = queue

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            result = decode_result_report(data)
        except ValueError:
            return
        self.queue.put_nowait(result)


class Coordinator:
    def __init__(
        self,
        *,
        nodes: list[Node],
        settings: Settings,
        export_path: Path | None = None,
        record_path: Path | None = None,
        history_path: Path | None = None,
        proxy_url: str | None = None,
        use_env_proxy: bool = True,
    ) -> None:
        self.nodes = nodes
        self.settings = settings
        self.export_path = export_path
        self.record_path = record_path
        self.history_path = history_path
        self.proxy_url = proxy_url
        self.use_env_proxy = use_env_proxy
        self.local_node = Node(
            id=socket.gethostname(),
            host=socket.gethostname(),
            port=1,
            name=socket.gethostname(),
            agent=False,
        )
        self.network_context = detect_network_context()
        self.matrix = MatrixStore(history_window=settings.history_window)
        self.analyzer = Analyzer(settings)
        self.alerts: list[Alert] = []
        self.clusters: list[Cluster] = []
        self._last_cluster_at = 0.0
        self.total_probes_sent = 0
        self.sequence = itertools.count(1)
        self.resolver = DNSResolver(settings.dns_cache_ttl_s)
        self.stop_event = asyncio.Event()
        self.report_queue: asyncio.Queue[ProbeResult] = asyncio.Queue()
        self.report_transport: asyncio.DatagramTransport | None = None
        self.split_brain: SplitBrainDiagnosis | None = None
        recorder_nodes = list({node.id: node for node in [*self.nodes, self.local_node]}.values())
        self.recorder: ProbeRecorder | None = None
        if record_path or history_path:
            self.recorder = ProbeRecorder(
                history_path=history_path,
                replay_path=record_path,
                nodes=recorder_nodes,
            )
            self.recorder.open()

    async def run_probe_cycle(self) -> list[ProbeResult]:
        resolved_pairs = await asyncio.gather(
            *(self._resolve_target(node) for node in self.nodes),
            return_exceptions=True,
        )
        resolved_map: dict[str, dict[str, str]] = {}
        for node, resolved in zip(self.nodes, resolved_pairs, strict=False):
            if isinstance(resolved, dict):
                resolved_map[node.id] = resolved
        await self._fingerprint_nodes()
        tasks = []
        for node in self.nodes:
            sequence = next(self.sequence)
            if node.agent:
                task = probe_agent(
                    node,
                    source_id=self.local_node.id,
                    timeout=self.settings.probe_timeout_s,
                    sequence=sequence,
                    node_id_hash=self.local_node.short_id_hash,
                )
            else:
                task = self._probe_tcp_target(
                    node,
                    sequence=sequence,
                    resolved=resolved_map.get(node.id, {}),
                )
            tasks.append(task)

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        results: list[ProbeResult] = []
        for node, result in zip(self.nodes, raw_results, strict=False):
            if isinstance(result, ProbeResult):
                results.append(result)
            else:
                now = time.time_ns()
                results.append(
                    ProbeResult(
                        source_id=self.local_node.id,
                        target_id=node.id,
                        sequence=next(self.sequence),
                        sent_at=now,
                        received_at=now,
                        rtt_ms=None,
                        success=False,
                        error=str(result),
                        probe_type=ProbeType.UDP if node.agent else ProbeType.TCP,
                    )
                )
        loopback = await probe_loopback(
            timeout=min(self.settings.probe_timeout_s, 1.0),
            sequence=next(self.sequence),
            source_id=self.local_node.id,
        )
        results.append(loopback)
        if self.settings.split_brain_enabled and not any(node.agent for node in self.nodes):
            self.split_brain = await diagnose_split_brain(
                timeout=min(self.settings.probe_timeout_s, 1.0)
            )
        self.total_probes_sent += len(results)
        for result in results:
            self.ingest(result)
        await self.export_snapshot()
        return results

    async def _resolve_target(self, node: Node) -> dict[str, str]:
        addresses = await self.resolver.resolve_all(node.host)
        if "IPv4" in addresses:
            node.resolved_ip = addresses["IPv4"]
        elif "IPv6" in addresses:
            node.resolved_ip = addresses["IPv6"]
        return addresses

    async def _probe_tcp_target(
        self,
        node: Node,
        *,
        sequence: int,
        resolved: dict[str, str],
    ) -> ProbeResult:
        if (
            self.settings.protocol_race_enabled
            and not self.proxy_url
            and "IPv4" in resolved
            and "IPv6" in resolved
        ):
            v4_result, v6_result = await asyncio.gather(
                probe_tcp(
                    node,
                    source_id=self.local_node.id,
                    timeout=self.settings.probe_timeout_s,
                    sequence=sequence,
                    resolved_ip=resolved["IPv4"],
                    proxy_url=self.proxy_url,
                    use_env_proxy=self.use_env_proxy,
                    ip_version="IPv4",
                ),
                probe_tcp(
                    node,
                    source_id=self.local_node.id,
                    timeout=self.settings.probe_timeout_s,
                    sequence=sequence + 100000,
                    resolved_ip=resolved["IPv6"],
                    proxy_url=self.proxy_url,
                    use_env_proxy=self.use_env_proxy,
                    ip_version="IPv6",
                ),
            )
            chosen = _prefer_result(v4_result, v6_result)
            chosen.ipv4_rtt_ms = v4_result.rtt_ms if v4_result.success else None
            chosen.ipv6_rtt_ms = v6_result.rtt_ms if v6_result.success else None
            return chosen
        ip_version = "IPv6" if ":" in (node.resolved_ip or "") and node.resolved_ip else "IPv4"
        return await probe_tcp(
            node,
            source_id=self.local_node.id,
            timeout=self.settings.probe_timeout_s,
            sequence=sequence,
            resolved_ip=node.resolved_ip,
            proxy_url=self.proxy_url,
            use_env_proxy=self.use_env_proxy,
            ip_version=ip_version,
        )

    async def run_agentless(self) -> None:
        while not self.stop_event.is_set():
            await self.run_probe_cycle()
            await asyncio.sleep(self.settings.probe_interval_s)

    async def run_distributed(
        self,
        *,
        listen_host: str,
        listen_port: int,
        public_host: str | None = None,
        push_config: bool = True,
    ) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _ResultProtocol(self.report_queue),
            local_addr=(listen_host, listen_port),
        )
        self.report_transport = transport

        resolved_public_host = self._resolve_public_host(
            listen_host=listen_host,
            public_host=public_host,
        )
        if push_config:
            await asyncio.gather(
                *(self.resolver.resolve_node(node) for node in self.nodes),
                return_exceptions=True,
            )
            await push_agent_configuration(
                self.nodes,
                coordinator_host=resolved_public_host,
                coordinator_port=listen_port,
                settings=self.settings,
            )

        try:
            while not self.stop_event.is_set():
                try:
                    result = await asyncio.wait_for(self.report_queue.get(), timeout=0.25)
                except asyncio.TimeoutError:
                    continue
                self.total_probes_sent += 1
                self.ingest(result)
                await self.export_snapshot()
        finally:
            if self.report_transport:
                self.report_transport.close()

    def ingest(self, result: ProbeResult) -> None:
        self.matrix.update(result)
        self.alerts = self.analyzer.evaluate(self.matrix)
        self._maybe_recompute_clusters()
        if self.recorder:
            self.recorder.record(result)
        logger.debug(
            "probe_result",
            source_id=result.source_id,
            target_id=result.target_id,
            success=result.success,
            rtt_ms=result.rtt_ms,
            error=result.error,
        )

    def stop(self) -> None:
        self.stop_event.set()
        if self.recorder:
            self.recorder.close()

    def reset_runtime(self) -> None:
        self.matrix = MatrixStore(history_window=self.settings.history_window)
        self.analyzer = Analyzer(self.settings)
        self.alerts = []
        self.clusters = []
        self._last_cluster_at = 0.0
        self.total_probes_sent = 0

    def source_order(self) -> list[str]:
        extra_sources = [
            cell.source_id
            for cell in self.matrix.iter_cells()
            if cell.source_id not in {node.id for node in self.nodes}
            and cell.source_id != self.local_node.id
        ]
        if any(node.agent for node in self.nodes):
            return list(dict.fromkeys([node.id for node in self.nodes] + extra_sources))
        return list(dict.fromkeys([self.local_node.id] + extra_sources))

    def target_order(self) -> list[str]:
        configured = [node.id for node in self.nodes]
        extra_targets = [
            cell.target_id
            for cell in self.matrix.iter_cells()
            if cell.target_id not in configured
        ]
        return list(dict.fromkeys(configured + extra_targets))

    def node_map(self) -> dict[str, Node]:
        mapping = {node.id: node for node in self.nodes}
        mapping[self.local_node.id] = self.local_node
        return mapping

    def snapshot(self) -> dict[str, Any]:
        matrix = {}
        for cell in self.matrix.iter_cells():
            matrix[f"{cell.source_id}->{cell.target_id}"] = {
                "p50": cell.p50,
                "p99": cell.p99,
                "loss": cell.loss_pct,
                "jitter": cell.jitter_ms,
                "min": cell.min_rtt,
                "max": cell.max_rtt,
                "error": cell.last_error,
                "asymmetric": cell.asymmetric,
                "asymmetry_ratio": cell.asymmetry_ratio,
            }
        return {
            "timestamp": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
            "nodes": [node.model_dump(mode="json") for node in self.nodes],
            "matrix": matrix,
            "clusters": [cluster.model_dump(mode="json") for cluster in self.clusters],
            "alerts": [alert.model_dump(mode="json") for alert in self.alerts],
        }

    def heatmap_rows(self, source_id: str, target_id: str) -> list[dict[str, float | int | str]]:
        cell = self.matrix.get(source_id, target_id)
        if not cell:
            return []
        buckets: dict[tuple[int, int], dict[str, float | int | str]] = {}
        for sample_ts, sample in cell.history:
            stamp = dt.datetime.fromtimestamp(sample_ts)
            key = (stamp.weekday(), stamp.hour)
            bucket = buckets.setdefault(
                key,
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "dow": stamp.weekday(),
                    "hour": stamp.hour,
                    "_total": 0.0,
                    "_count": 0,
                    "_loss": 0,
                },
            )
            if sample is None:
                bucket["_loss"] = int(bucket["_loss"]) + 1
            else:
                bucket["_total"] = float(bucket["_total"]) + sample
                bucket["_count"] = int(bucket["_count"]) + 1
        rows: list[dict[str, float | int | str]] = []
        for key in sorted(buckets):
            bucket = buckets[key]
            count = int(bucket["_count"])
            losses = int(bucket["_loss"])
            total_samples = count + losses
            rows.append(
                {
                    "source_id": bucket["source_id"],
                    "target_id": bucket["target_id"],
                    "dow": bucket["dow"],
                    "hour": bucket["hour"],
                    "avg_rtt_ms": (float(bucket["_total"]) / count) if count else 0.0,
                    "loss_pct": ((losses / total_samples) * 100) if total_samples else 0.0,
                    "samples": total_samples,
                }
            )
        return rows

    def export_heatmap_csv(self, output_path: Path, *, source_id: str, target_id: str) -> None:
        rows = self.heatmap_rows(source_id, target_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "source_id",
                    "target_id",
                    "dow",
                    "hour",
                    "avg_rtt_ms",
                    "loss_pct",
                    "samples",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)

    async def export_snapshot(self) -> None:
        if not self.export_path:
            return
        self.export_path.parent.mkdir(parents=True, exist_ok=True)
        self.export_path.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")

    def _default_public_host(self) -> str:
        hostname = socket.gethostname()
        try:
            return socket.gethostbyname(hostname)
        except OSError:
            return hostname

    def _resolve_public_host(
        self,
        *,
        listen_host: str,
        public_host: str | None,
    ) -> str:
        if public_host:
            return public_host
        if listen_host not in {"0.0.0.0", "::"}:
            return listen_host
        return self._default_public_host()

    async def _fingerprint_nodes(self) -> None:
        candidates = [
            node
            for node in self.nodes
            if not node.agent and node.fingerprint is None
        ]
        if not candidates:
            return
        fingerprints = await asyncio.gather(
            *(
                fingerprint_service(
                    node,
                    timeout=min(self.settings.probe_timeout_s, 1.0),
                    resolved_ip=node.resolved_ip,
                )
                for node in candidates
            ),
            return_exceptions=True,
        )
        for node, fingerprint in zip(candidates, fingerprints, strict=False):
            if isinstance(fingerprint, str):
                node.fingerprint = fingerprint

    def _maybe_recompute_clusters(self) -> None:
        now = time.monotonic()
        if self.clusters and now - self._last_cluster_at < self.settings.cluster_recompute_s:
            return
        node_ids = list(dict.fromkeys(self.source_order() + self.target_order()))
        if not node_ids:
            return
        self.clusters = compute_clusters(
            node_ids,
            self.matrix,
            threshold_ms=self.settings.cluster_threshold_ms,
        )
        self._last_cluster_at = now
