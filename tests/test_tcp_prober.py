import asyncio
import socket

from meshping.models.node import Node
from meshping.prober.tcp import probe_tcp


def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def test_probe_tcp_success() -> None:
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        node = Node(id="srv", host="127.0.0.1", port=port, name="srv")
        result = await probe_tcp(node, source_id="local", timeout=1.0, sequence=1)
        assert result.success is True
        assert result.rtt_ms is not None
        assert result.error is None
    finally:
        server.close()
        await server.wait_closed()


async def test_probe_tcp_connection_refused() -> None:
    port = free_port()
    node = Node(id="srv", host="127.0.0.1", port=port, name="srv")
    result = await probe_tcp(node, source_id="local", timeout=0.5, sequence=1)
    assert result.success is False
    assert result.error == "connection_refused"


async def test_probe_tcp_via_http_connect_proxy() -> None:
    requests: list[bytes] = []

    async def handle_proxy(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        data = await reader.readuntil(b"\r\n\r\n")
        requests.append(data)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    proxy_server = await asyncio.start_server(handle_proxy, "127.0.0.1", 0)
    try:
        proxy_port = proxy_server.sockets[0].getsockname()[1]
        node = Node(id="github", host="github.com", port=443, name="github")
        result = await probe_tcp(
            node,
            source_id="local",
            timeout=1.0,
            sequence=1,
            proxy_url=f"http://127.0.0.1:{proxy_port}",
        )

        assert result.success is True
        assert result.rtt_ms is not None
        assert requests
        assert requests[0].startswith(b"CONNECT github.com:443 HTTP/1.1")
    finally:
        proxy_server.close()
        await proxy_server.wait_closed()


async def test_probe_tcp_reports_proxy_http_failure() -> None:
    async def handle_proxy(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 403 Forbidden\r\n\r\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    proxy_server = await asyncio.start_server(handle_proxy, "127.0.0.1", 0)
    try:
        proxy_port = proxy_server.sockets[0].getsockname()[1]
        node = Node(id="dns", host="8.8.8.8", port=53, name="dns")
        result = await probe_tcp(
            node,
            source_id="local",
            timeout=1.0,
            sequence=1,
            proxy_url=f"http://127.0.0.1:{proxy_port}",
        )

        assert result.success is False
        assert result.error == "proxy_connect_http_403"
    finally:
        proxy_server.close()
        await proxy_server.wait_closed()
