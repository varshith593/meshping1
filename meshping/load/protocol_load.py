from __future__ import annotations

from urllib.parse import urlparse

from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult
from meshping.prober.http import probe_http
from meshping.prober.tcp import probe_tcp
from meshping.prober.udp import probe_udp_agent


def node_to_url(node: Node) -> str:
    scheme = "https" if node.port == 443 else "http"
    return f"{scheme}://{node.host}:{node.port}/"


def url_to_node(url: str) -> Node:
    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError(f"Invalid URL: {url}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return Node(id=url, host=parsed.hostname, port=port, name=parsed.hostname)


async def probe_by_protocol(
    target: Node | str,
    *,
    protocol: str,
    source_id: str,
    timeout: float,
    sequence: int,
    session: object | None = None,
) -> ProbeResult:
    protocol = protocol.lower()
    if protocol == "http":
        url = target if isinstance(target, str) else node_to_url(target)
        return await probe_http(
            url,
            session=session,
            timeout=timeout,
            source_id=source_id,
            target_id=url,
            sequence=sequence,
        )
    if isinstance(target, str):
        node = url_to_node(target)
    else:
        node = target
    if protocol == "udp":
        return await probe_udp_agent(
            node,
            source_id=source_id,
            timeout=timeout,
            sequence=sequence,
            node_id_hash=0,
        )
    return await probe_tcp(
        node,
        source_id=source_id,
        timeout=timeout,
        sequence=sequence,
        use_env_proxy=False,
    )
