from __future__ import annotations

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from meshping.models.alert import Severity


def render_replay_progress(
    *,
    current_offset_s: float,
    total_duration_s: float,
    speed: float,
    paused: bool,
    markers: list[tuple[float, str, Severity]] | None = None,
) -> Group:
    width = 40
    ratio = 0.0 if total_duration_s <= 0 else min(max(current_offset_s / total_duration_s, 0.0), 1.0)
    filled = int(ratio * width)
    chars = ["█" if index < filled else "░" for index in range(width)]
    for offset_s, _label, severity in markers or []:
        if total_duration_s <= 0:
            continue
        position = min(width - 1, max(0, int(offset_s / total_duration_s * width)))
        chars[position] = _marker_for(severity)
    bar = "".join(chars)
    status = "PAUSED" if paused else "PLAYING"
    help_text = "SPACE pause/resume | ← slower | → faster | g goto | q quit"
    text = Text()
    text.append(f"{status}  speed={speed:.1f}x  {current_offset_s:.1f}s/{total_duration_s:.1f}s\n")
    text.append(f"[{bar}] {ratio * 100:.0f}%\n")
    text.append(help_text, style="dim")
    return Group(Panel(text, title="Replay"))


def _marker_for(severity: Severity) -> str:
    if severity == Severity.CRITICAL:
        return "✗"
    if severity == Severity.WARNING:
        return "⚠"
    return "●"
