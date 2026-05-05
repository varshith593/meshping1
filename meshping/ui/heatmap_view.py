from __future__ import annotations

from rich.console import Group
from rich.table import Table
from rich.text import Text

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HEAT_CHARS = {
    "fast": ("░░", "green"),
    "medium": ("▒▒", "yellow"),
    "slow": ("▓▓", "orange3"),
    "bad": ("██", "red"),
    "loss": ("■■", "bright_red"),
    "empty": ("··", "grey50"),
}


def render_heatmap_table(
    rows: list[dict[str, float | int | str]],
    *,
    title: str = "Time-of-Day Heatmap",
) -> Group:
    table = Table(expand=True, title="Time-of-Day Heatmap")
    table.add_column("Day")
    for hour in range(24):
        table.add_column(f"{hour:02d}", justify="center", no_wrap=True, width=3)
    by_key = {(int(row["dow"]), int(row["hour"])): row for row in rows}
    hot_windows: list[tuple[int, int, int]] = []
    for dow, label in enumerate(DAYS):
        values = [label]
        run_start: int | None = None
        for hour in range(24):
            row = by_key.get((dow, hour))
            if not row:
                chars, color = HEAT_CHARS["empty"]
                values.append(Text(chars, style=color))
                run_start = None
                continue
            avg = float(row["avg_rtt_ms"] or 0.0)
            loss = float(row["loss_pct"] or 0.0)
            chars, color = _classify_heat(avg, loss)
            values.append(Text(chars, style=color))
            is_hot = chars in {"▓▓", "██", "■■"}
            if is_hot and run_start is None:
                run_start = hour
            elif not is_hot and run_start is not None:
                hot_windows.append((dow, run_start, hour - 1))
                run_start = None
        if run_start is not None:
            hot_windows.append((dow, run_start, 23))
        table.add_row(*values)
    insight = _build_insight(hot_windows)
    legend = Text("░ <2ms  ▒ 2-10ms  ▓ 10-50ms  █ >50ms  ■ loss", style="dim")
    if title:
        table.title = title
    return Group(table, legend, Text(insight, style="yellow" if hot_windows else "dim"))


def _classify_heat(avg_rtt_ms: float, loss_pct: float) -> tuple[str, str]:
    if loss_pct > 1.0:
        return HEAT_CHARS["loss"]
    if avg_rtt_ms < 2.0:
        return HEAT_CHARS["fast"]
    if avg_rtt_ms < 10.0:
        return HEAT_CHARS["medium"]
    if avg_rtt_ms < 50.0:
        return HEAT_CHARS["slow"]
    return HEAT_CHARS["bad"]


def _build_insight(hot_windows: list[tuple[int, int, int]]) -> str:
    if not hot_windows:
        return "Insight: no consistent hot window detected yet."
    largest = max(hot_windows, key=lambda item: item[2] - item[1])
    day, start_hour, end_hour = largest
    return (
        f"Insight: hottest window is {DAYS[day]} {start_hour:02d}:00-{end_hour:02d}:59."
    )
