from __future__ import annotations

from meshping.models.alert import Severity


def latency_style(
    value: float | None, *, error: str | None = None, diagonal: bool = False
) -> str:
    if diagonal:
        return "dim"
    if error == "timeout":
        return "bold red"
    if error == "connection_refused":
        return "magenta"
    if error and error.startswith("proxy_"):
        return "yellow"
    if value is None:
        return "dim"
    if value < 1:
        return "bright_green"
    if value < 5:
        return "green"
    if value < 20:
        return "yellow"
    if value < 100:
        return "orange3"
    return "red"


def severity_style(severity: Severity) -> str:
    if severity == Severity.CRITICAL:
        return "bold red"
    if severity == Severity.WARNING:
        return "yellow"
    return "cyan"
