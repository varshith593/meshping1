from meshping.mesh.asymmetry import detect_asymmetries
from meshping.mesh.matrix import MatrixStore
from meshping.models.probe_result import ProbeResult, ProbeType


def make_result(source: str, target: str, rtt_ms: float, sequence: int) -> ProbeResult:
    return ProbeResult(
        source_id=source,
        target_id=target,
        sequence=sequence,
        sent_at=sequence,
        received_at=sequence + 1,
        rtt_ms=rtt_ms,
        success=True,
        probe_type=ProbeType.UDP,
    )


def test_detect_asymmetries_marks_both_directions() -> None:
    matrix = MatrixStore()
    matrix.update(make_result("a", "b", 10.0, 1))
    matrix.update(make_result("b", "a", 40.0, 2))

    findings = detect_asymmetries(matrix, threshold=2.0)

    assert len(findings) == 1
    assert findings[0].ratio == 4.0
    assert matrix.get("a", "b").asymmetric is True
    assert matrix.get("b", "a").asymmetric is True
