from __future__ import annotations

import socket

from meshping.local.doctor import default_gateway
from meshping.models.node import Node


def sandbox_targets() -> list[Node]:
    nodes = [
        Node(id="cloudflare", name="cloudflare", host="1.1.1.1", port=443),
        Node(id="google", name="google", host="8.8.8.8", port=443),
    ]
    gateway = default_gateway()
    if gateway:
        nodes.append(Node(id="router", name="router", host=gateway, port=_router_port(gateway)))
    return nodes


def _router_port(host: str) -> int:
    for port in (53, 80, 443):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.15)
            if sock.connect_ex((host, port)) == 0:
                return port
    return 53
