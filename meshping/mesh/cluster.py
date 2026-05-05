from __future__ import annotations

from collections import deque
from itertools import combinations

from meshping.mesh.matrix import MatrixStore
from meshping.models.cluster import Cluster

CLUSTER_COLORS = [
    "cyan",
    "orange3",
    "purple",
    "gold1",
    "red",
    "green",
    "blue",
    "magenta",
]


def compute_clusters(
    node_ids: list[str],
    matrix: MatrixStore,
    *,
    threshold_ms: float = 5.0,
) -> list[Cluster]:
    graph: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for left, right in combinations(node_ids, 2):
        if _mutual_p50_below(matrix, left, right, threshold_ms):
            graph[left].add(right)
            graph[right].add(left)

    clusters: list[Cluster] = []
    visited: set[str] = set()
    for node_id in node_ids:
        if node_id in visited:
            continue
        members = _component(graph, node_id, visited)
        color = CLUSTER_COLORS[len(clusters) % len(CLUSTER_COLORS)]
        clusters.append(
            Cluster(
                id=f"cluster-{len(clusters) + 1}",
                node_ids=members,
                color=color,
            )
        )
    return clusters


def _mutual_p50_below(
    matrix: MatrixStore,
    left: str,
    right: str,
    threshold_ms: float,
) -> bool:
    forward = matrix.get(left, right)
    reverse = matrix.get(right, left)
    if forward and reverse and forward.p50 is not None and reverse.p50 is not None:
        return max(forward.p50, reverse.p50) <= threshold_ms
    if forward and forward.p50 is not None:
        return forward.p50 <= threshold_ms
    if reverse and reverse.p50 is not None:
        return reverse.p50 <= threshold_ms
    return False


def _component(
    graph: dict[str, set[str]],
    start: str,
    visited: set[str],
) -> list[str]:
    queue: deque[str] = deque([start])
    visited.add(start)
    members: list[str] = []
    while queue:
        node_id = queue.popleft()
        members.append(node_id)
        for neighbor in sorted(graph[node_id]):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append(neighbor)
    return members
