from meshping.load.stats import sparkline, summarize_results
from meshping.cli._common import parse_load_distribution
from meshping.models.probe_result import ProbeResult, ProbeType
from meshping.models.stress_result import StressStatus


def make_result(sequence: int, rtt_ms: float | None, success: bool = True) -> ProbeResult:
    return ProbeResult(
        source_id="local",
        target_id="target",
        sequence=sequence,
        sent_at=sequence,
        received_at=sequence + 1 if success else None,
        rtt_ms=rtt_ms,
        success=success,
        error=None if success else "timeout",
        probe_type=ProbeType.TCP,
    )


def test_summarize_results_classifies_loss_as_breaking() -> None:
    results = [make_result(1, 1.0), make_result(2, None, success=False)]

    summary = summarize_results(
        results,
        load_level_pps=100,
        baseline_p99=1.0,
        baseline_p50=0.5,
        duration_s=1.0,
    )

    assert summary.loss_pct == 50.0
    assert summary.status == StressStatus.BREAKING
    assert summary.achieved_pps == 2.0
    assert summary.degradation_pct == 100.0


def test_sparkline_renders_rtt_trend() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    rendered = sparkline(values)
    assert rendered
    assert len(rendered) == len(values)


def test_parse_load_distribution_allows_named_targets() -> None:
    distribution = parse_load_distribution(
        ("web=localhost:8080=70%", "db=localhost:5432=30%")
    )

    assert distribution[0][0].id == "web"
    assert distribution[0][1] == 70.0
    assert distribution[1][0].id == "db"
