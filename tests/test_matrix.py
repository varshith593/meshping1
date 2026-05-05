from meshping.mesh.matrix import MatrixStore
from meshping.models.probe_result import ProbeResult, ProbeType


def make_result(
    *,
    rtt_ms: float | None,
    success: bool,
    error: str | None = None,
    sequence: int = 1,
) -> ProbeResult:
    return ProbeResult(
        source_id="src",
        target_id="dst",
        sequence=sequence,
        sent_at=sequence,
        received_at=sequence + 1 if success else None,
        rtt_ms=rtt_ms,
        success=success,
        error=error,
        probe_type=ProbeType.TCP,
    )


def test_matrix_updates_statistics_and_loss() -> None:
    matrix = MatrixStore(history_window=10)
    samples = [1.0, 2.0, 3.0, None, 4.0]
    for index, sample in enumerate(samples, start=1):
        matrix.update(
            make_result(
                rtt_ms=sample,
                success=sample is not None,
                error=None if sample is not None else "timeout",
                sequence=index,
            )
        )

    cell = matrix.get("src", "dst")
    assert cell is not None
    assert cell.p50 == 2.5
    assert cell.p99 == 4.0
    assert cell.min_rtt == 1.0
    assert cell.max_rtt == 4.0
    assert cell.loss_pct == 20.0
    assert cell.jitter_ms == 1.0


def test_matrix_sets_baseline_after_ten_samples() -> None:
    matrix = MatrixStore(history_window=20)
    for sequence in range(1, 11):
        matrix.update(make_result(rtt_ms=float(sequence), success=True, sequence=sequence))

    cell = matrix.get("src", "dst")
    assert cell is not None
    assert cell.baseline_p50 == 5.5


def test_matrix_tracks_protocol_race_and_stability() -> None:
    matrix = MatrixStore(history_window=10)
    result = make_result(rtt_ms=8.0, success=True, sequence=1)
    result.ipv4_rtt_ms = 8.0
    result.ipv6_rtt_ms = 18.5
    result.ip_version = "IPv4"
    matrix.update(result)

    cell = matrix.get("src", "dst")
    assert cell is not None
    assert cell.preferred_ip_version == "IPv4"
    assert cell.protocol_race_note == "IPv6 slower than IPv4"
    assert cell.stability_pct is not None
