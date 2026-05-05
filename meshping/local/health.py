from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalHealth:
    platform: str
    interface: str | None = None
    cpu_load_1m: float | None = None
    cpu_load_5m: float | None = None
    memory_used_pct: float | None = None
    tcp_retransmits: int | None = None
    sockets_used: int | None = None
    tcp_time_wait: int | None = None
    tcp_close_wait: int | None = None
    tx_queue_len: int | None = None
    tx_dropped: int | None = None
    rx_missed: int | None = None
    note: str | None = None


def read_local_health(interface: str | None = None) -> LocalHealth:
    system = platform.system()
    if system == "Linux":
        return _read_linux_health(interface=interface)
    if system == "Darwin":
        return _read_macos_health()
    return LocalHealth(platform=system, note="local health is not implemented for this OS")


def _read_linux_health(interface: str | None) -> LocalHealth:
    tcp_retransmits = _read_tcp_retransmits()
    sockets_used = _read_sockstat_used()
    tcp_time_wait, tcp_close_wait = _read_tcp_states()
    net_base = Path("/sys/class/net")
    iface = interface or (_first_non_loopback_interface(net_base) if net_base.exists() else None)
    tx_dropped, rx_missed = _read_interface_errors(iface)
    return LocalHealth(
        platform="Linux",
        interface=iface,
        cpu_load_1m=_load_average(0),
        cpu_load_5m=_load_average(1),
        memory_used_pct=_linux_memory_used_pct(),
        tcp_retransmits=tcp_retransmits,
        sockets_used=sockets_used,
        tcp_time_wait=tcp_time_wait,
        tcp_close_wait=tcp_close_wait,
        tx_queue_len=_read_tx_queue_len(iface),
        tx_dropped=tx_dropped,
        rx_missed=rx_missed,
    )


def _read_macos_health() -> LocalHealth:
    retransmits = None
    try:
        output = subprocess.check_output(["netstat", "-s"], text=True, timeout=2)
        for line in output.splitlines():
            lowered = line.strip().lower()
            if "retransmit timeout" in lowered or "retransmitted" in lowered:
                number = lowered.split()[0]
                if number.isdigit():
                    retransmits = int(number)
                    break
    except (OSError, subprocess.SubprocessError):
        pass
    return LocalHealth(
        platform="Darwin",
        interface=_default_macos_interface(),
        cpu_load_1m=_load_average(0),
        cpu_load_5m=_load_average(1),
        memory_used_pct=_macos_memory_used_pct(),
        tcp_retransmits=retransmits,
        note="macOS exposes fewer counters without elevated tools",
    )


def _read_tcp_retransmits() -> int | None:
    path = Path("/proc/net/snmp")
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for header, values in zip(lines, lines[1:], strict=False):
        if not header.startswith("Tcp:") or not values.startswith("Tcp:"):
            continue
        fields = header.split()[1:]
        nums = values.split()[1:]
        if "RetransSegs" in fields:
            return int(nums[fields.index("RetransSegs")])
    return None


def _read_sockstat_used() -> int | None:
    path = Path("/proc/net/sockstat")
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("sockets:"):
            parts = line.split()
            if "used" in parts:
                return int(parts[parts.index("used") + 1])
    return None


def _read_tcp_states() -> tuple[int | None, int | None]:
    path = Path("/proc/net/tcp")
    if not path.exists():
        return None, None
    time_wait = 0
    close_wait = 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        state = parts[3]
        if state == "06":
            time_wait += 1
        elif state == "08":
            close_wait += 1
    return time_wait, close_wait


def _read_interface_errors(interface: str | None) -> tuple[int | None, int | None]:
    base = Path("/sys/class/net")
    if not base.exists():
        return None, None
    if not interface:
        return None, None
    stats = base / interface / "statistics"
    return _read_int(stats / "tx_dropped"), _read_int(stats / "rx_missed_errors")


def _first_non_loopback_interface(base: Path) -> str | None:
    for child in sorted(base.iterdir()):
        if child.name != "lo":
            return child.name
    return None


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _read_tx_queue_len(interface: str | None) -> int | None:
    if not interface:
        return None
    return _read_int(Path("/sys/class/net") / interface / "tx_queue_len")


def _default_macos_interface() -> str | None:
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


def _load_average(index: int) -> float | None:
    try:
        return os.getloadavg()[index]
    except (AttributeError, OSError, IndexError):
        return None


def _linux_memory_used_pct() -> float | None:
    path = Path("/proc/meminfo")
    if not path.exists():
        return None
    values: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        parts = line.replace(":", "").split()
        if len(parts) >= 2 and parts[1].isdigit():
            values[parts[0]] = int(parts[1])
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        return None
    used = total - available
    return (used / total) * 100


def _macos_memory_used_pct() -> float | None:
    try:
        total = int(
            subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"],
                text=True,
                timeout=2,
            ).strip()
        )
        output = subprocess.check_output(["vm_stat"], text=True, timeout=2)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    page_size = 4096
    for line in output.splitlines():
        if "page size of" in line:
            try:
                page_size = int(line.split("page size of", 1)[1].split()[0])
            except (IndexError, ValueError):
                page_size = 4096
            continue
    pages: dict[str, int] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        raw = raw.strip().rstrip(".")
        if raw.isdigit():
            pages[key.strip()] = int(raw)
    free = pages.get("Pages free", 0) + pages.get("Pages speculative", 0)
    inactive = pages.get("Pages inactive", 0)
    available = (free + inactive) * page_size
    if total <= 0:
        return None
    used = max(total - available, 0)
    return (used / total) * 100
