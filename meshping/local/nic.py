from __future__ import annotations

import platform
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from meshping.load.stats import sparkline


@dataclass
class NICSample:
    ts: float
    tx_bytes: int
    rx_bytes: int
    tx_dropped: int
    rx_missed: int
    speed_mbps: int | None = None
    irq_coalesce_usecs: int | None = None


@dataclass
class NICWatcher:
    interface: str
    samples: deque[NICSample] = field(default_factory=lambda: deque(maxlen=60))

    def sample(self) -> NICSample | None:
        sample = read_nic_sample(self.interface)
        if sample:
            self.samples.append(sample)
        return sample

    def tx_drop_sparkline(self) -> str:
        return sparkline(_deltas([sample.tx_dropped for sample in self.samples]))

    def rx_miss_sparkline(self) -> str:
        return sparkline(_deltas([sample.rx_missed for sample in self.samples]))

    def tx_utilization_sparkline(self) -> str:
        return sparkline(sample.utilization_tx_pct for sample in sample_deltas(self.samples))

    def rx_utilization_sparkline(self) -> str:
        return sparkline(sample.utilization_rx_pct for sample in sample_deltas(self.samples))

    def latest_delta(self) -> "NICDelta | None":
        deltas = sample_deltas(self.samples)
        return deltas[-1] if deltas else None


def read_nic_sample(interface: str) -> NICSample | None:
    system = platform.system()
    if system == "Linux":
        return _read_linux_nic_sample(interface)
    if system == "Darwin":
        return _read_macos_nic_sample(interface)
    return None


@dataclass
class NICDelta:
    utilization_tx_pct: float
    utilization_rx_pct: float
    tx_dropped_per_sec: float
    rx_missed_per_sec: float
    speed_mbps: int | None
    irq_coalesce_usecs: int | None


def default_interface() -> str | None:
    linux_route = Path("/proc/net/route")
    if linux_route.exists():
        for line in linux_route.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]:
            fields = line.split()
            if len(fields) > 1 and fields[1] == "00000000":
                return fields[0]
    try:
        output = subprocess.check_output(
            ["route", "-n", "get", "default"],
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in output.splitlines():
        if "interface:" in line:
            return line.split("interface:", 1)[1].strip()
    return None


def sample_deltas(samples: deque[NICSample]) -> list[NICDelta]:
    items = list(samples)
    deltas: list[NICDelta] = []
    for previous, current in zip(items, items[1:], strict=False):
        elapsed = max(current.ts - previous.ts, 1e-6)
        speed_bps = (current.speed_mbps or 0) * 1_000_000
        tx_pct = 0.0
        rx_pct = 0.0
        if speed_bps > 0:
            tx_pct = min(
                100.0,
                ((current.tx_bytes - previous.tx_bytes) * 8 / elapsed) / speed_bps * 100,
            )
            rx_pct = min(
                100.0,
                ((current.rx_bytes - previous.rx_bytes) * 8 / elapsed) / speed_bps * 100,
            )
        deltas.append(
            NICDelta(
                utilization_tx_pct=tx_pct,
                utilization_rx_pct=rx_pct,
                tx_dropped_per_sec=max(current.tx_dropped - previous.tx_dropped, 0) / elapsed,
                rx_missed_per_sec=max(current.rx_missed - previous.rx_missed, 0) / elapsed,
                speed_mbps=current.speed_mbps,
                irq_coalesce_usecs=current.irq_coalesce_usecs,
            )
        )
    return deltas


def _deltas(values: list[int]) -> list[float]:
    if len(values) < 2:
        return []
    return [float(curr - prev) for prev, curr in zip(values, values[1:], strict=False)]


def _read_linux_nic_sample(interface: str) -> NICSample | None:
    base = Path("/sys/class/net") / interface
    stats = base / "statistics"
    try:
        return NICSample(
            ts=time.time(),
            tx_bytes=int((stats / "tx_bytes").read_text(encoding="utf-8").strip()),
            rx_bytes=int((stats / "rx_bytes").read_text(encoding="utf-8").strip()),
            tx_dropped=int((stats / "tx_dropped").read_text(encoding="utf-8").strip()),
            rx_missed=int(
                (stats / "rx_missed_errors").read_text(encoding="utf-8").strip()
            ),
            speed_mbps=_read_int(base / "speed"),
            irq_coalesce_usecs=_read_int(base / "gro_flush_timeout"),
        )
    except (OSError, ValueError):
        return None


def _read_macos_nic_sample(interface: str) -> NICSample | None:
    try:
        output = subprocess.check_output(
            ["netstat", "-ibn"],
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in output.splitlines()[1:]:
        fields = line.split()
        if not fields or fields[0] != interface or len(fields) < 11:
            continue
        try:
            return NICSample(
                ts=time.time(),
                tx_bytes=int(fields[9]),
                rx_bytes=int(fields[6]),
                tx_dropped=int(fields[-2]) if fields[-2].isdigit() else 0,
                rx_missed=int(fields[-1]) if fields[-1].isdigit() else 0,
                speed_mbps=None,
                irq_coalesce_usecs=None,
            )
        except ValueError:
            continue
    return None


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
