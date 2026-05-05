from meshping.mesh.cluster import compute_clusters
from meshping.mesh.matrix import MatrixStore
from meshping.models.probe_result import ProbeResult, ProbeType


def result(source: str, target: str, rtt_ms: float, sequence: int) -> ProbeResult:
    return ProbeResult(
        source_id=source,
        target_id=target,
        sequence=sequence,
        sent_at=sequence,
        received_at=sequence + 1,
        rtt_ms=rtt_ms,
        success=True,
        probe_type=ProbeType.TCP,
    )


def test_compute_clusters_uses_mutual_latency_components() -> None:
    matrix = MatrixStore()
    matrix.update(result("a", "b", 2.0, 1))
    matrix.update(result("b", "a", 3.0, 2))
    matrix.update(result("b", "c", 20.0, 3))
    matrix.update(result("c", "b", 20.0, 4))

    clusters = compute_clusters(["a", "b", "c"], matrix, threshold_ms=5.0)
    members = [set(cluster.node_ids) for cluster in clusters]

    assert {"a", "b"} in members
    assert {"c"} in members
