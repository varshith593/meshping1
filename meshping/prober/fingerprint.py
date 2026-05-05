from __future__ import annotations

import asyncio
import contextlib
import re

from meshping.models.node import Node

READ_LIMIT = 64
READ_TIMEOUT_S = 0.2


async def fingerprint_service(
    node: Node,
    *,
    timeout: float = 1.0,
    resolved_ip: str | None = None,
) -> str | None:
    host = resolved_ip or node.resolved_ip or node.host
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host=host, port=node.port),
            timeout=timeout,
        )
    except OSError:
        return None
    except asyncio.TimeoutError:
        return None

    try:
        banner = await _read_banner(reader, writer, node)
        return identify_service(banner, port=node.port)
    finally:
        writer.close()
        with contextlib.suppress(OSError, ConnectionError, asyncio.TimeoutError):
            await writer.wait_closed()


async def _read_banner(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    node: Node,
) -> bytes:
    try:
        banner = await asyncio.wait_for(reader.read(READ_LIMIT), timeout=READ_TIMEOUT_S)
    except asyncio.TimeoutError:
        banner = b""
    if banner:
        return banner
    if node.port in {80, 8080, 8000, 5000}:
        writer.write(
            f"HEAD / HTTP/1.1\r\nHost: {node.host}\r\nConnection: close\r\n\r\n".encode(
                "ascii"
            )
        )
        await writer.drain()
        try:
            return await asyncio.wait_for(reader.read(READ_LIMIT), timeout=READ_TIMEOUT_S)
        except asyncio.TimeoutError:
            return b""
    if node.port == 6379:
        writer.write(b"PING\r\n")
        await writer.drain()
        try:
            return await asyncio.wait_for(reader.read(READ_LIMIT), timeout=READ_TIMEOUT_S)
        except asyncio.TimeoutError:
            return b""
    return b""


def identify_service(banner: bytes, *, port: int | None = None) -> str | None:
    if not banner:
        return _service_from_port(port)
    text = banner.decode("latin1", errors="ignore")
    upper = text.upper()
    if text.startswith("SSH-2.0"):
        return "SSH/OpenSSH" if "OpenSSH" in text else "SSH"
    if "NOAUTH" in upper or "PONG" in upper:
        return "Redis"
    if "HTTP/1." in upper or "HTTP/2" in upper:
        server = _server_header(text)
        return server or "HTTP"
    if banner.startswith(b"\x00\x00\x00"):
        return "PostgreSQL"
    if port == 5432:
        return "PostgreSQL"
    if port == 9092:
        return "Kafka"
    return _service_from_port(port)


def _server_header(text: str) -> str | None:
    match = re.search(r"^Server:\s*([^\r\n]+)", text, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None


def _service_from_port(port: int | None) -> str | None:
    return {
        22: "SSH",
        53: "DNS",
        80: "HTTP",
        443: "HTTPS",
        5432: "PostgreSQL",
        6379: "Redis",
        9092: "Kafka",
    }.get(port or 0)

