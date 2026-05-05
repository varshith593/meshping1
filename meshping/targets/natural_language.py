from __future__ import annotations

import socket

from meshping.models.node import Node
from meshping.targets.sandbox import sandbox_targets


def resolve_query_nodes(query: str) -> list[Node]:
    lowered = query.strip().lower()
    if not lowered:
        return sandbox_targets()

    nodes: dict[str, Node] = {}
    if any(term in lowered for term in {"dns", "internet", "cloudflare", "google"}):
        for node in sandbox_targets():
            if node.id != "router":
                nodes[node.id] = node
    if any(term in lowered for term in {"router", "wifi", "gateway"}):
        for node in sandbox_targets():
            if node.id == "router":
                nodes[node.id] = node
    if any(term in lowered for term in {"backend", "api", "frontend", "local app", "localhost"}):
        local = _local_target("backend", 8080)
        if local:
            nodes[local.id] = local
    if any(term in lowered for term in {"postgres", "database", "db"}):
        local = _local_target("postgres", 5432)
        if local:
            nodes[local.id] = local
    if any(term in lowered for term in {"ollama", "llm", "ai"}):
        local = _local_target("ollama", 11434)
        if local:
            nodes[local.id] = local
    if not nodes:
        return sandbox_targets()
    return list(nodes.values())


def _local_target(name: str, port: int) -> Node | None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.15)
        if sock.connect_ex(("127.0.0.1", port)) != 0:
            return None
    return Node(id=name, name=name, host="127.0.0.1", port=port)
