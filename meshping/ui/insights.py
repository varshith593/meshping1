from __future__ import annotations

from rich.text import Text

from meshping.models.matrix_cell import MatrixCell


USAGE_PROFILES = ("work", "gaming", "video")


def normalize_profile(profile: str | None) -> str:
    lowered = (profile or "work").strip().lower()
    return lowered if lowered in USAGE_PROFILES else "work"


def next_profile(profile: str | None) -> str:
    current = normalize_profile(profile)
    index = USAGE_PROFILES.index(current)
    return USAGE_PROFILES[(index + 1) % len(USAGE_PROFILES)]


def describe_cell(cell: MatrixCell, profile: str = "work") -> str:
    profile = normalize_profile(profile)
    if cell.last_error == "timeout":
        return "Offline or blocked"
    if cell.loss_pct >= 5:
        return "Packet loss - check WiFi"
    if cell.loss_pct >= 1:
        return "Loss detected - calls may crackle"
    if cell.protocol_race_note and "slower" in cell.protocol_race_note:
        return cell.protocol_race_note
    if profile == "gaming" and (cell.jitter_ms or 0.0) > 5:
        return "Jitter too high for gaming"
    if profile == "video" and cell.loss_pct == 0 and (cell.p50 or 0.0) <= 100:
        return "Fine for streaming"
    if cell.jitter_ms is not None and cell.jitter_ms >= 15:
        return "Buffer warning"
    if cell.p50 is None:
        return "Waiting for samples"
    if cell.p50 <= 20 and (cell.jitter_ms or 0.0) <= 5:
        return "Good for gaming"
    if cell.p50 <= 80 and (cell.jitter_ms or 0.0) <= 10:
        return "Good for calls"
    if cell.p50 <= 150:
        return "Usable but laggy"
    return "Slow path - check ISP/VPN"


def status_label(cell: MatrixCell, profile: str = "work") -> str:
    profile = normalize_profile(profile)
    if cell.last_error == "timeout" or cell.loss_pct >= 5:
        return "BAD"
    if profile == "gaming":
        if (cell.jitter_ms or 0.0) > 5:
            return "BAD"
        if (cell.p50 or 0.0) >= 50:
            return "WARN"
    if profile == "video":
        if cell.loss_pct == 0 and (cell.p50 or 0.0) <= 100:
            return "GOOD"
        if cell.loss_pct >= 1 or (cell.jitter_ms or 0.0) > 20:
            return "WARN"
    if cell.loss_pct >= 1:
        return "WARN"
    if cell.jitter_ms is not None and cell.jitter_ms >= 15:
        return "WARN"
    if cell.p50 is not None and cell.p50 >= 100:
        return "WARN"
    return "GOOD"


def status_style(cell: MatrixCell, profile: str = "work") -> str:
    label = status_label(cell, profile)
    if label == "BAD":
        return "bold red"
    if label == "WARN":
        return "yellow"
    return "green"


def cell_summary(cell: MatrixCell) -> str:
    if cell.p50 is None:
        return status_label(cell)
    jitter = cell.jitter_ms or 0.0
    if cell.preferred_ip_version:
        return f"{cell.p50:.2f}±{jitter:.2f}ms {cell.preferred_ip_version}"
    return f"{cell.p50:.2f}±{jitter:.2f}ms"


def health_score(cells: list[MatrixCell], profile: str = "work") -> int:
    profile = normalize_profile(profile)
    if not cells:
        return 100
    penalties: list[float] = []
    for cell in cells:
        penalty = 0.0
        penalty += min(cell.loss_pct * 1.2, 45)
        if cell.last_error:
            penalty += 18
        if cell.jitter_ms:
            divisor = 2 if profile == "gaming" else 4 if profile == "video" else 3
            penalty += min(cell.jitter_ms / divisor, 15)
        if cell.p50:
            divisor = 40 if profile == "video" else 20 if profile == "gaming" else 25
            penalty += min(cell.p50 / divisor, 20)
        penalties.append(penalty)
    score = 100.0 - (sum(penalties) / max(len(penalties), 1))
    return max(0, min(100, round(score)))


def health_score_text(score: int, profile: str = "work") -> Text:
    style = "green" if score >= 80 else "yellow" if score >= 55 else "bold red"
    return Text(f"health={score}/100 profile={normalize_profile(profile)}", style=style)


def support_summary(cell: MatrixCell, profile: str = "work") -> str:
    status = status_label(cell, profile)
    note = describe_cell(cell, profile)
    stability = f"{cell.stability_pct}%" if cell.stability_pct is not None else "unknown"
    protocol = cell.protocol_race_note or (cell.preferred_ip_version or "single-stack")
    latency = f"{cell.p50:.2f}ms" if cell.p50 is not None else "n/a"
    return (
        f"{cell.source_id}->{cell.target_id}: status={status}, latency={latency}, "
        f"loss={cell.loss_pct:.1f}%, stability={stability}, protocol={protocol}, note={note}"
    )
