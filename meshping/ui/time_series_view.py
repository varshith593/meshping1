from __future__ import annotations

from rich.console import Group
from rich.table import Table
from rich.text import Text

from meshping.models.matrix_cell import MatrixCell


def render_time_series(cell: MatrixCell, *, title: str | None = None) -> Group:
    table = Table(expand=True, title=title or f"RTT History {cell.source_id} -> {cell.target_id}")
    table.add_column("Window")
    table.add_column("Trend")
    table.add_column("p50", justify="right")
    table.add_column("p99", justify="right")
    table.add_column("Loss", justify="right")
    points = [sample for _, sample in list(cell.history)[-60:] if sample is not None]
    trend = _sparkline(points)
    table.add_row(
        "Last 60 samples",
        trend,
        f"{cell.p50:.2f}ms" if cell.p50 is not None else "-",
        f"{cell.p99:.2f}ms" if cell.p99 is not None else "-",
        f"{cell.loss_pct:.1f}%",
    )
    note = Text()
    if cell.rolling_5min_p50 is not None:
        note.append(f"Rolling 5m p50: {cell.rolling_5min_p50:.2f}ms", style="cyan")
    if cell.baseline_p50 is not None:
        if note.plain:
            note.append("  ")
        note.append(f"Baseline: {cell.baseline_p50:.2f}ms", style="dim")
    return Group(table, note)


def _sparkline(points: list[float]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    if not points:
        return "─" * 20
    if len(points) == 1:
        return blocks[3] * 20
    low = min(points)
    high = max(points)
    if high == low:
        return blocks[3] * min(len(points), 20)
    tail = points[-20:]
    return "".join(
        blocks[min(int((point - low) / (high - low) * (len(blocks) - 1)), len(blocks) - 1)]
        for point in tail
    )
