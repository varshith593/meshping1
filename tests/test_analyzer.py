from meshping.config.settings import Settings
from meshping.mesh.analyzer import Analyzer
from meshping.mesh.matrix import MatrixStore
from meshping.models.alert import AlertType, Severity
from meshping.models.matrix_cell import MatrixCell
from meshping.models.probe_result import ProbeResult, ProbeType


def make_result(
    source: str,
    target: str,
    *,
    rtt_ms: float | None,
    success: bool,
    sequence: int,
    error: str | None = None,
) -> ProbeResult:
    return ProbeResult(
        source_id=source,
        target_id=target,
        sequence=sequence,
        sent_at=sequence,
        received_at=sequence + 1 if success else None,
        rtt_ms=rtt_ms,
        success=success,
        error=error,
        probe_type=ProbeType.UDP,
    )


def test_analyzer_detects_spike_and_loss() -> None:
    settings = Settings(anomaly_spike_factor=3.0, anomaly_loss_pct=5.0)
    matrix = MatrixStore(history_window=20)
    analyzer = Analyzer(settings)

    for sequence in range(1, 11):
        matrix.update(make_result("a", "b", rtt_ms=1.0, success=True, sequence=sequence))
    for sequence in range(11, 21):
        matrix.update(make_result("a", "b", rtt_ms=10.0, success=True, sequence=sequence))
    for sequence in range(21, 24):
        matrix.update(
            make_result("a", "b", rtt_ms=None, success=False, error="timeout", sequence=sequence)
        )

    alerts = analyzer.evaluate(matrix)
    alert_types = {alert.alert_type for alert in alerts}
    assert AlertType.SPIKE in alert_types
    assert AlertType.LOSS in alert_types


def test_analyzer_detects_asymmetry_and_recovery() -> None:
    settings = Settings(anomaly_spike_factor=3.0, anomaly_loss_pct=5.0)
    matrix = MatrixStore(history_window=20)
    analyzer = Analyzer(settings)

    for sequence in range(1, 11):
        matrix.update(make_result("a", "b", rtt_ms=5.0, success=True, sequence=sequence))
        matrix.update(make_result("b", "a", rtt_ms=20.0, success=True, sequence=sequence))

    alerts = analyzer.evaluate(matrix)
    asymmetry = [alert for alert in alerts if alert.alert_type == AlertType.ASYMMETRY]
    assert asymmetry
    assert asymmetry[0].severity == Severity.INFO

    down_matrix = MatrixStore(history_window=20)
    for sequence in range(1, 11):
        down_matrix.update(
            make_result(
                "a",
                "c",
                rtt_ms=None,
                success=False,
                error="timeout",
                sequence=sequence,
            )
        )
    alerts = analyzer.evaluate(down_matrix)
    assert any(alert.alert_type == AlertType.NODE_DOWN for alert in alerts)

    recovered = MatrixStore(history_window=20)
    for sequence in range(1, 3):
        recovered.update(make_result("a", "c", rtt_ms=2.0, success=True, sequence=sequence))
    alerts = analyzer.evaluate(recovered)
    assert any(alert.alert_type == AlertType.RECOVERY for alert in alerts)


def test_analyzer_detects_route_change_and_recovery() -> None:
    settings = Settings(
        route_change_factor=3.0,
        route_change_persist_minutes=1,
        route_change_reset_factor=1.5,
        route_change_check_s=0.001,
    )
    analyzer = Analyzer(settings)
    matrix = MatrixStore()
    cell = MatrixCell(source_id="web", target_id="db")
    cell.baseline_p50 = 2.0
    cell.rolling_5min_p50 = 8.0
    cell.p50 = 8.0
    matrix.cells[("web", "db")] = cell

    alerts = analyzer.evaluate(matrix)
    assert any(alert.alert_type == AlertType.ROUTE_CHANGE for alert in alerts)
    assert cell.route_change_fired is True

    cell.rolling_5min_p50 = 2.5
    cell.p50 = 2.5
    cell.last_route_change_check_at = 0.0
    alerts = analyzer.evaluate(matrix)
    assert any(alert.alert_type == AlertType.RECOVERY for alert in alerts)
    assert cell.route_change_fired is False
