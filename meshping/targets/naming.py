from __future__ import annotations

import ipaddress
import socket

from meshping.models.node import Node


KNOWN_LOCAL_PORTS = {
    3000: "frontend",
    5173: "frontend",
    5432: "postgres",
    6379: "redis",
    8080: "backend",
    9092: "kafka",
    11434: "ollama",
}


def apply_auto_names(nodes: list[Node]) -> list[Node]:
    for node in nodes:
        if node.name and node.name != node.host:
            continue
        guessed = guess_target_name(node.host, node.port)
        if guessed:
            node.name = guessed
    return nodes


def guess_target_name(host: str, port: int) -> str | None:
    lowered = host.lower()
    if lowered in {"127.0.0.1", "localhost", "::1"}:
        return KNOWN_LOCAL_PORTS.get(port, "localhost")
    if port in KNOWN_LOCAL_PORTS:
        try:
            parsed = ipaddress.ip_address(host)
        except ValueError:
            parsed = None
        if parsed and parsed.is_private:
            label = _reverse_lookup(host)
            if label:
                return label
            return KNOWN_LOCAL_PORTS[port]
    return _reverse_lookup(host)


def _reverse_lookup(host: str) -> str | None:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return None
    try:
        hostname, _, _ = socket.gethostbyaddr(host)
    except OSError:
        return None
    short = hostname.split(".", 1)[0].strip()
    return short or None
