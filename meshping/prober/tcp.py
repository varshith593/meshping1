from __future__ import annotations

import asyncio
import base64
import ssl
import time

from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult, ProbeType
from meshping.prober.proxy import ProxyConfig, proxy_for_target


async def probe_tcp(
    target: Node,
    *,
    source_id: str,
    timeout: float,
    sequence: int,
    resolved_ip: str | None = None,
    proxy_url: str | None = None,
    use_env_proxy: bool = True,
    ip_version: str | None = None,
) -> ProbeResult:
    host = resolved_ip or target.resolved_ip or target.host
    try:
        proxy = proxy_for_target(
            target.host,
            target.port,
            explicit_proxy_url=proxy_url,
            use_env_proxy=use_env_proxy,
        )
    except ValueError as exc:
        now = time.time_ns()
        return ProbeResult(
            source_id=source_id,
            target_id=target.id,
            sequence=sequence,
            sent_at=now,
            received_at=now,
            rtt_ms=None,
            success=False,
            error=f"invalid_proxy: {exc}",
            probe_type=ProbeType.TCP,
            ip_version=ip_version,
        )

    if proxy:
        return await _probe_tcp_via_http_proxy(
            target,
            proxy=proxy,
            source_id=source_id,
            timeout=timeout,
            sequence=sequence,
        )

    sent_at = time.time_ns()
    try:
        connect_coro = asyncio.open_connection(host=host, port=target.port)
        reader, writer = await asyncio.wait_for(connect_coro, timeout=timeout)
        received_at = time.time_ns()
        writer.close()
        await writer.wait_closed()
        rtt_ms = (received_at - sent_at) / 1_000_000
        return ProbeResult(
            source_id=source_id,
            target_id=target.id,
            sequence=sequence,
            sent_at=sent_at,
            received_at=received_at,
            rtt_ms=rtt_ms,
            success=True,
            error=None,
            probe_type=ProbeType.TCP,
            ip_version=ip_version,
        )
    except ConnectionRefusedError:
        received_at = time.time_ns()
        return ProbeResult(
            source_id=source_id,
            target_id=target.id,
            sequence=sequence,
            sent_at=sent_at,
            received_at=received_at,
            rtt_ms=(received_at - sent_at) / 1_000_000,
            success=False,
            error="connection_refused",
            probe_type=ProbeType.TCP,
            ip_version=ip_version,
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
            probe_type=ProbeType.TCP,
            ip_version=ip_version,
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
            probe_type=ProbeType.TCP,
            ip_version=ip_version,
        )


async def _probe_tcp_via_http_proxy(
    target: Node,
    *,
    proxy: ProxyConfig,
    source_id: str,
    timeout: float,
    sequence: int,
) -> ProbeResult:
    sent_at = time.time_ns()
    try:
        ssl_context = ssl.create_default_context() if proxy.scheme == "https" else None
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(proxy.host, proxy.port, ssl=ssl_context),
            timeout=timeout,
        )
        request = _build_connect_request(target, proxy)
        writer.write(request)
        await asyncio.wait_for(writer.drain(), timeout=timeout)
        response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout)
        received_at = time.time_ns()
        status_line = response.split(b"\r\n", 1)[0].decode("iso-8859-1", errors="replace")
        status_code = _parse_status_code(status_line)
        writer.close()
        await writer.wait_closed()

        if 200 <= status_code < 300:
            return ProbeResult(
                source_id=source_id,
                target_id=target.id,
                sequence=sequence,
                sent_at=sent_at,
                received_at=received_at,
                rtt_ms=(received_at - sent_at) / 1_000_000,
                success=True,
                error=None,
                probe_type=ProbeType.TCP,
            )

        return ProbeResult(
            source_id=source_id,
            target_id=target.id,
            sequence=sequence,
            sent_at=sent_at,
            received_at=received_at,
            rtt_ms=None,
            success=False,
            error=f"proxy_connect_http_{status_code}",
            probe_type=ProbeType.TCP,
        )
    except ConnectionRefusedError:
        received_at = time.time_ns()
        return ProbeResult(
            source_id=source_id,
            target_id=target.id,
            sequence=sequence,
            sent_at=sent_at,
            received_at=received_at,
            rtt_ms=None,
            success=False,
            error="proxy_connection_refused",
            probe_type=ProbeType.TCP,
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
            error="proxy_timeout",
            probe_type=ProbeType.TCP,
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
            error=f"proxy_error: {exc.strerror or exc.__class__.__name__.lower()}",
            probe_type=ProbeType.TCP,
        )


def _build_connect_request(target: Node, proxy: ProxyConfig) -> bytes:
    authority = f"{target.host}:{target.port}"
    headers = [
        f"CONNECT {authority} HTTP/1.1",
        f"Host: {authority}",
        "User-Agent: meshping/0.1",
        "Proxy-Connection: Keep-Alive",
    ]
    if proxy.username is not None:
        password = proxy.password or ""
        token = base64.b64encode(f"{proxy.username}:{password}".encode("utf-8")).decode(
            "ascii"
        )
        headers.append(f"Proxy-Authorization: Basic {token}")
    return ("\r\n".join(headers) + "\r\n\r\n").encode("ascii")


def _parse_status_code(status_line: str) -> int:
    parts = status_line.split()
    if len(parts) < 2:
        return 0
    try:
        return int(parts[1])
    except ValueError:
        return 0
