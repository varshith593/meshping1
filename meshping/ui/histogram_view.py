from __future__ import annotations

from rich.console import Group
from rich.table import Table
from rich.text import Text

from meshping.models.matrix_cell import MatrixCell


def render_histogram(cell: MatrixCell, *, bins: int = 10) -> Group:
    samples = [sample for sample in cell.samples if sample is not None]
    table = Table(expand=True, title=f"RTT Distribution {cell.source_id} -> {cell.target_id}")
    table.add_column("Bucket")
    table.add_column("Count", justify="right")
    table.add_column("Bar")
    if not samples:
        table.add_row("-", "0", "[dim]no RTT samples[/dim]")
        return Group(table)
    low = min(samples)
    high = max(samples)
    if high == low:
        table.add_row(f"{low:.2f}ms", str(len(samples)), "█" * min(len(samples), 20))
        return Group(table)
    width = (high - low) / bins
    counts = [0] * bins
    for sample in samples:
        index = min(int((sample - low) / width), bins - 1)
        counts[index] += 1
    for index, count in enumerate(counts):
        start = low + index * width
        end = start + width
        table.add_row(
            f"{start:.1f}-{end:.1f}ms",
            str(count),
            "█" * min(count, 20),
        )
    insight = Text(_histogram_insight(counts), style="yellow")
    return Group(table, insight)


def _histogram_insight(counts: list[int]) -> str:
    peaks = [index for index, count in enumerate(counts) if count == max(counts)]
    if len(peaks) >= 2 and abs(peaks[0] - peaks[-1]) >= 3:
        return "Bimodal distribution detected."
    return "Distribution is concentrated around a single latency mode."
