from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from meshping.models.alert import Severity
from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult, ProbeType
from meshping.storage.recorder import MPR_HEADER, MPR_MAGIC, MPR_RECORD


@dataclass(frozen=True)
class ReplayEvent:
    timestamp_s: float
    result: ProbeResult


@dataclass
class ReplayController:
    state: Literal["PLAYING", "PAUSED", "SEEKING"] = "PLAYING"
    speed: float = 1.0
    position_s: float = 0.0
    total_duration_s: float = 0.0
    pending_seek_s: float | None = None
    quit_requested: bool = False
    changed: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def paused(self) -> bool:
        return self.state == "PAUSED"

    def toggle_pause(self) -> None:
        self.state = "PLAYING" if self.state == "PAUSED" else "PAUSED"
        self.changed.set()

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.5, min(speed, 4.0))
        self.changed.set()

    def seek(self, offset_s: float) -> None:
        self.pending_seek_s = max(0.0, min(offset_s, self.total_duration_s))
        self.state = "SEEKING"
        self.changed.set()

    def resume(self) -> None:
        self.state = "PLAYING"
        self.changed.set()


class ReplaySession:
    def __init__(self, *, nodes: list[Node], events: list[ReplayEvent]) -> None:
        self.nodes = nodes
        self.events = events

    @classmethod
    def from_file(cls, path: Path) -> "ReplaySession":
        with path.open("rb") as handle:
            header = handle.read(MPR_HEADER.size)
            magic, version, node_json_len, created_at_ns = MPR_HEADER.unpack(header)
            if magic != MPR_MAGIC or version != 1:
                raise ValueError("Unsupported meshping replay file")
            nodes_payload = handle.read(node_json_len)
            nodes = [Node.model_validate(item) for item in json.loads(nodes_payload)]
            events: list[ReplayEvent] = []
            index = 1
            while chunk := handle.read(MPR_RECORD.size):
                if len(chunk) != MPR_RECORD.size:
                    raise ValueError("Truncated replay record")
                timestamp_s, source_index, target_index, rtt_us, success = MPR_RECORD.unpack(chunk)
                source = nodes[source_index]
                target = nodes[target_index]
                rtt_ms = None if rtt_us < 0 else rtt_us / 1000
                received_at = int(timestamp_s * 1_000_000_000)
                sent_at = received_at if rtt_ms is None else received_at - int(rtt_ms * 1_000_000)
                events.append(
                    ReplayEvent(
                        timestamp_s=timestamp_s,
                        result=ProbeResult(
                            source_id=source.id,
                            target_id=target.id,
                            sequence=index,
                            sent_at=sent_at,
                            received_at=received_at if success else None,
                            rtt_ms=rtt_ms,
                            success=bool(success),
                            error=None if success else "replay_loss",
                            probe_type=ProbeType.TCP,
                        ),
                    )
                )
                index += 1
        return cls(nodes=nodes, events=events)

    async def play(self, *, speed: float = 1.0):
        previous: float | None = None
        for event in self.events:
            if previous is not None:
                await asyncio.sleep(max(0.0, event.timestamp_s - previous) / speed)
            previous = event.timestamp_s
            yield event.result

    @property
    def start_ts(self) -> float:
        return self.events[0].timestamp_s if self.events else 0.0

    @property
    def total_duration_s(self) -> float:
        if len(self.events) < 2:
            return 0.0
        return self.events[-1].timestamp_s - self.events[0].timestamp_s

    def index_for_offset(self, offset_s: float) -> int:
        if not self.events:
            return 0
        absolute = self.start_ts + offset_s
        low = 0
        high = len(self.events)
        while low < high:
            mid = (low + high) // 2
            if self.events[mid].timestamp_s < absolute:
                low = mid + 1
            else:
                high = mid
        return low

    def rebuild_until_offset(self, coordinator, offset_s: float) -> int:
        coordinator.reset_runtime()
        start_ts = self.start_ts
        index = 0
        for index, event in enumerate(self.events):
            if event.timestamp_s - start_ts > offset_s:
                return index
            coordinator.ingest(event.result)
        return len(self.events)

    def progress_markers(self) -> list[tuple[float, str, Severity]]:
        markers: list[tuple[float, str, Severity]] = []
        baselines: dict[tuple[str, str], list[float]] = {}
        consecutive_failures: dict[tuple[str, str], int] = {}
        for event in self.events:
            key = (event.result.source_id, event.result.target_id)
            offset_s = event.timestamp_s - self.start_ts
            if event.result.success and event.result.rtt_ms is not None:
                values = baselines.setdefault(key, [])
                values.append(event.result.rtt_ms)
                consecutive_failures[key] = 0
                if len(values) >= 10:
                    baseline = sum(values[:10]) / 10
                    if baseline > 0 and event.result.rtt_ms >= baseline * 3:
                        markers.append((offset_s, "spike", Severity.WARNING))
            else:
                consecutive_failures[key] = consecutive_failures.get(key, 0) + 1
                if consecutive_failures[key] == 10:
                    markers.append((offset_s, "node_down", Severity.CRITICAL))
        return markers
