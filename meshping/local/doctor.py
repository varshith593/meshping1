from __future__ import annotations

import asyncio
import platform
import socket
import subprocess
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from meshping.local.health import read_local_health
from meshping.local.loopback import probe_loopback
from meshping.models.node import Node
from meshping.prober.icmp import probe_icmp
from meshping.prober.tcp import probe_tcp


class DoctorStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: DoctorStatus
    value: str
    explanation: str
    recommendation: str = ""


@dataclass(frozen=True)
class SplitBrainDiagnosis:
    gateway_rtt_ms: float | None
    internet_rtt_ms: float | None
    diagnosis: str
    recommendation: str


async def run_doctor(*, ports: list[int] | None = None, timeout: float = 2.0) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    checks.append(await check_loopback(timeout=timeout))
    checks.append(await check_default_gateway(timeout=timeout))
    checks.append(await check_split_brain(timeout=timeout))
    checks.append(await check_dns_resolution(timeout=timeout))
    checks.append(await check_primary_dns(timeout=timeout))
    checks.append(await check_internet(timeout=timeout))
    checks.append(await check_ipv6(timeout=timeout))
    checks.append(await check_mtu_path(timeout=timeout))
    checks.extend(check_local_health())
    for port in ports or [80, 443, 22, 9092]:
        checks.append(await check_outbound_port(port, timeout=timeout))
    return checks


async def check_loopback(*, timeout: float) -> DoctorCheck:
    result = await probe_loopback(timeout=timeout)
    if result.success and result.rtt_ms is not None and result.rtt_ms < 0.5:
        return DoctorCheck("Loopback", DoctorStatus.PASS, f"{result.rtt_ms:.3f}ms", "Local TCP stack is responsive.")
    if result.success and result.rtt_ms is not None:
        return DoctorCheck(
            "Loopback",
            DoctorStatus.WARN,
            f"{result.rtt_ms:.3f}ms",
            "Loopback latency is elevated, so external measurements may be inflated.",
            "Close CPU-heavy processes and rerun the test.",
        )
    return DoctorCheck("Loopback", DoctorStatus.FAIL, result.error or "failed", "Local TCP probe failed.")


async def check_dns_resolution(*, timeout: float) -> DoctorCheck:
    started = time.monotonic()
    try:
        await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo("localhost", None),
            timeout=timeout,
        )
    except Exception as exc:
        return DoctorCheck(
            "DNS",
            DoctorStatus.FAIL,
            exc.__class__.__name__,
            "Name resolution failed.",
            "Check /etc/resolv.conf or your system DNS settings.",
        )
    elapsed_ms = (time.monotonic() - started) * 1000
    status = DoctorStatus.PASS if elapsed_ms < 50 else DoctorStatus.WARN
    return DoctorCheck("DNS", status, f"{elapsed_ms:.2f}ms", "Resolver answered localhost lookup.")


async def check_default_gateway(*, timeout: float) -> DoctorCheck:
    gateway = default_gateway()
    if not gateway:
        return DoctorCheck(
            "Default Gateway",
            DoctorStatus.WARN,
            "unknown",
            "Could not identify the default gateway.",
            "Check routing table with `netstat -rn` or `ip route`.",
        )
    result = await probe_icmp(
        Node(id="gateway", host=gateway, port=1, name="gateway"),
        source_id="doctor",
        timeout=timeout,
        sequence=1,
    )
    if result.success and result.rtt_ms is not None:
        status = DoctorStatus.PASS if result.rtt_ms < 5 else DoctorStatus.WARN
        return DoctorCheck(
            "Default Gateway",
            status,
            f"{gateway} {result.rtt_ms:.2f}ms",
            "Gateway responded to ICMP.",
        )
    return DoctorCheck(
        "Default Gateway",
        DoctorStatus.WARN,
        gateway,
        "Gateway did not answer ICMP; this can be normal on some networks.",
    )


async def check_primary_dns(*, timeout: float) -> DoctorCheck:
    resolver = primary_resolver()
    if not resolver:
        return DoctorCheck(
            "Primary DNS",
            DoctorStatus.WARN,
            "unknown",
            "Could not find a nameserver in /etc/resolv.conf.",
        )
    node = Node(id="primary-dns", host=resolver, port=53, name=resolver)
    result = await probe_tcp(
        node,
        source_id="doctor",
        timeout=timeout,
        sequence=53,
        use_env_proxy=False,
    )
    if result.success or result.error == "connection_refused":
        value = f"{resolver} {result.rtt_ms:.2f}ms" if result.rtt_ms else resolver
        return DoctorCheck(
            "Primary DNS",
            DoctorStatus.PASS,
            value,
            "Resolver address is reachable on TCP/53.",
        )
    return DoctorCheck(
        "Primary DNS",
        DoctorStatus.WARN,
        f"{resolver} {result.error or 'failed'}",
        "Resolver address did not answer TCP/53; UDP DNS may still work.",
        "If DNS lookups are slow, try a local DNS cache or a different resolver.",
    )


async def diagnose_split_brain(*, timeout: float) -> SplitBrainDiagnosis:
    gateway = default_gateway()
    if not gateway:
        return SplitBrainDiagnosis(
            gateway_rtt_ms=None,
            internet_rtt_ms=None,
            diagnosis="Gateway unknown",
            recommendation="Check the local routing table before blaming the ISP.",
        )
    gateway_node = Node(id="gateway", host=gateway, port=1, name="gateway")
    internet_node = Node(id="google-dns", host="8.8.8.8", port=1, name="8.8.8.8")
    gateway_result, internet_result = await asyncio.gather(
        probe_icmp(gateway_node, source_id="doctor", timeout=timeout, sequence=111),
        probe_icmp(internet_node, source_id="doctor", timeout=timeout, sequence=112),
    )
    gateway_rtt = gateway_result.rtt_ms if gateway_result.success else None
    internet_rtt = internet_result.rtt_ms if internet_result.success else None
    if gateway_rtt is not None and gateway_rtt > 15:
        return SplitBrainDiagnosis(
            gateway_rtt_ms=gateway_rtt,
            internet_rtt_ms=internet_rtt,
            diagnosis="WiFi interference",
            recommendation="The local gateway is slow. Check WiFi signal, channel congestion, or move closer to the router.",
        )
    if gateway_rtt is not None and internet_rtt is not None and internet_rtt > 80:
        return SplitBrainDiagnosis(
            gateway_rtt_ms=gateway_rtt,
            internet_rtt_ms=internet_rtt,
            diagnosis="ISP congestion",
            recommendation="Your router is fast but the public path is slow. Check ISP load, VPN exits, or upstream congestion.",
        )
    if gateway_rtt is None and internet_rtt is None:
        return SplitBrainDiagnosis(
            gateway_rtt_ms=None,
            internet_rtt_ms=None,
            diagnosis="Path unavailable",
            recommendation="ICMP is blocked or the network is down. Retry on a different network or use doctor outbound port checks.",
        )
    return SplitBrainDiagnosis(
        gateway_rtt_ms=gateway_rtt,
        internet_rtt_ms=internet_rtt,
        diagnosis="Path healthy",
        recommendation="Local gateway and public DNS both respond normally.",
    )


async def check_split_brain(*, timeout: float) -> DoctorCheck:
    diagnosis = await diagnose_split_brain(timeout=timeout)
    if diagnosis.diagnosis == "WiFi interference":
        status = DoctorStatus.WARN
    elif diagnosis.diagnosis == "ISP congestion":
        status = DoctorStatus.WARN
    elif diagnosis.diagnosis == "Path unavailable":
        status = DoctorStatus.FAIL
    else:
        status = DoctorStatus.PASS
    value = (
        f"gw={diagnosis.gateway_rtt_ms:.2f}ms internet={diagnosis.internet_rtt_ms:.2f}ms"
        if diagnosis.gateway_rtt_ms is not None and diagnosis.internet_rtt_ms is not None
        else diagnosis.diagnosis
    )
    return DoctorCheck(
        "Split-Brain",
        status,
        value,
        diagnosis.diagnosis,
        diagnosis.recommendation,
    )


async def check_internet(*, timeout: float) -> DoctorCheck:
    node = Node(id="cloudflare", host="1.1.1.1", port=443, name="1.1.1.1:443")
    result = await probe_tcp(node, source_id="doctor", timeout=timeout, sequence=1, use_env_proxy=False)
    if result.success:
        return DoctorCheck("Internet", DoctorStatus.PASS, f"{result.rtt_ms:.2f}ms", "TCP 443 is reachable.")
    return DoctorCheck(
        "Internet",
        DoctorStatus.WARN,
        result.error or "failed",
        "Could not connect to 1.1.1.1:443.",
        "Check firewall, VPN, captive portal, or upstream connectivity.",
    )


async def check_ipv6(*, timeout: float) -> DoctorCheck:
    node = Node(id="cloudflare-v6", host="2606:4700:4700::1111", port=443, name="IPv6")
    result = await probe_tcp(node, source_id="doctor", timeout=timeout, sequence=1, use_env_proxy=False)
    if result.success:
        return DoctorCheck("IPv6", DoctorStatus.PASS, f"{result.rtt_ms:.2f}ms", "IPv6 TCP connectivity works.")
    return DoctorCheck("IPv6", DoctorStatus.WARN, result.error or "failed", "IPv6 is unavailable or filtered.")


async def check_outbound_port(port: int, *, timeout: float) -> DoctorCheck:
    node = Node(id=f"port-{port}", host="8.8.8.8", port=port, name=f"8.8.8.8:{port}")
    result = await probe_tcp(node, source_id="doctor", timeout=timeout, sequence=port, use_env_proxy=False)
    if result.success or result.error == "connection_refused":
        return DoctorCheck(f"Outbound {port}", DoctorStatus.PASS, result.error or f"{result.rtt_ms:.2f}ms", "Outbound route is not silently dropping traffic.")
    return DoctorCheck(
        f"Outbound {port}",
        DoctorStatus.WARN,
        result.error or "failed",
        f"Outbound TCP port {port} may be filtered.",
        "Check local firewall, corporate proxy, VPN, or cloud egress rules.",
    )


async def check_mtu_path(*, timeout: float) -> DoctorCheck:
    large = await _ping_df("1.1.1.1", size=1472, timeout=timeout)
    if large is True:
        return DoctorCheck(
            "MTU Path",
            DoctorStatus.PASS,
            "1500-byte path",
            "A 1472-byte ICMP payload passed without fragmentation.",
        )
    small = await _ping_df("1.1.1.1", size=1200, timeout=timeout)
    if small is True:
        return DoctorCheck(
            "MTU Path",
            DoctorStatus.WARN,
            "below 1500",
            "Large no-fragment probe failed but smaller probe passed.",
            "Check VPN, tunnel, or cloud network MTU settings.",
        )
    return DoctorCheck(
        "MTU Path",
        DoctorStatus.WARN,
        "not measured",
        "No-fragment ping failed or is unsupported on this system/network.",
    )


def check_local_health() -> list[DoctorCheck]:
    health = read_local_health()
    checks: list[DoctorCheck] = []
    if health.tcp_retransmits is not None:
        status = DoctorStatus.WARN if health.tcp_retransmits > 0 else DoctorStatus.PASS
        checks.append(
            DoctorCheck(
                "TCP retransmits",
                status,
                str(health.tcp_retransmits),
                "Kernel TCP retransmit counter.",
                "Investigate packet loss or Wi-Fi quality if this rises during tests.",
            )
        )
    if health.tx_dropped is not None:
        status = DoctorStatus.WARN if health.tx_dropped > 0 else DoctorStatus.PASS
        checks.append(
            DoctorCheck(
                "NIC TX drops",
                status,
                str(health.tx_dropped),
                "Transmit drops reported by the local network interface.",
                "Treat load-test results as local-machine limited if drops increase.",
            )
        )
    if not checks:
        checks.append(
            DoctorCheck(
                "Local counters",
                DoctorStatus.WARN,
                health.note or health.platform,
                "Detailed local network counters are not available on this platform.",
            )
        )
    return checks


def default_gateway() -> str | None:
    linux_route = Path("/proc/net/route")
    if linux_route.exists():
        for line in linux_route.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 3 and parts[1] == "00000000":
                raw = bytes.fromhex(parts[2])
                return socket.inet_ntoa(raw[::-1])
    try:
        output = subprocess.check_output(["route", "-n", "get", "default"], text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in output.splitlines():
        if "gateway:" in line:
            return line.split("gateway:", 1)[1].strip()
    return None


def primary_resolver() -> str | None:
    path = Path("/etc/resolv.conf")
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            return parts[1]
    return None


async def _ping_df(host: str, *, size: int, timeout: float) -> bool | None:
    system = platform.system()
    if system == "Darwin":
        args = [
            "ping",
            "-D",
            "-s",
            str(size),
            "-c",
            "1",
            "-W",
            str(max(int(timeout * 1000), 1)),
            host,
        ]
    elif system == "Linux":
        args = [
            "ping",
            "-M",
            "do",
            "-s",
            str(size),
            "-c",
            "1",
            "-W",
            str(max(int(timeout), 1)),
            host,
        ]
    else:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError:
        return None
    try:
        await asyncio.wait_for(proc.communicate(), timeout=timeout + 1)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return False
    return proc.returncode == 0
