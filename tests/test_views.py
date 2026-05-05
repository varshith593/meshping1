from rich.console import Console

from meshping.ui.heatmap_view import render_heatmap_table


def test_heatmap_view_renders_density_blocks_and_insight() -> None:
    rows = [
        {"dow": 0, "hour": 8, "avg_rtt_ms": 1.2, "loss_pct": 0.0},
        {"dow": 0, "hour": 9, "avg_rtt_ms": 12.0, "loss_pct": 0.0},
        {"dow": 0, "hour": 10, "avg_rtt_ms": 60.0, "loss_pct": 0.0},
        {"dow": 0, "hour": 11, "avg_rtt_ms": 0.8, "loss_pct": 2.0},
    ]

    console = Console(record=True, width=140)
    console.print(render_heatmap_table(rows, title="Heatmap web1 -> db1"))
    output = console.export_text()

    assert "Heatmap web1 -> db1" in output
    assert "Insight:" in output
    assert any(block in output for block in ["░░", "▓▓", "██", "■■"])
