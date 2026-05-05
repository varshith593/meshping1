from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table

from meshping.local.doctor import DoctorStatus, run_doctor


@click.command("doctor")
@click.option("--ports", help="Comma-separated outbound TCP ports to check.")
@click.option("--output", "output_path", help="Write a plain-text report.")
@click.option("--timeout", default=2.0, show_default=True, type=float)
def doctor_command(ports: str | None, output_path: str | None, timeout: float) -> None:
    """Run local network self-diagnosis."""
    parsed_ports = _parse_ports(ports)
    checks = asyncio.run(run_doctor(ports=parsed_ports, timeout=timeout))
    console = Console(record=True)
    table = Table(title="meshping doctor", expand=True)
    table.add_column("Test")
    table.add_column("Status")
    table.add_column("Value")
    table.add_column("Explanation")
    table.add_column("Recommendation")
    for check in checks:
        table.add_row(
            check.name,
            _status(check.status),
            check.value,
            check.explanation,
            check.recommendation or "-",
        )
    console.print(table)
    console.print(_summary_panel(checks))
    if output_path:
        Path(output_path).write_text(console.export_text(), encoding="utf-8")


def _parse_ports(value: str | None) -> list[int] | None:
    if not value:
        return None
    try:
        ports = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise click.BadParameter("ports must be comma-separated integers") from exc
    if any(port < 1 or port > 65535 for port in ports):
        raise click.BadParameter("ports must be between 1 and 65535")
    return ports


def _status(status: DoctorStatus) -> str:
    if status == DoctorStatus.PASS:
        return "[green]PASS[/green]"
    if status == DoctorStatus.FAIL:
        return "[red]FAIL[/red]"
    return "[yellow]WARN[/yellow]"


def _summary_panel(checks) -> Panel:
    fails = [check for check in checks if check.status == DoctorStatus.FAIL]
    warns = [check for check in checks if check.status == DoctorStatus.WARN]
    body = Text()
    body.append(f"Pass: {len(checks) - len(fails) - len(warns)}  ", style="green")
    body.append(f"Warn: {len(warns)}  ", style="yellow")
    body.append(f"Fail: {len(fails)}\n", style="red" if fails else "green")
    recommendations = [check.recommendation for check in checks if check.recommendation][:3]
    if recommendations:
        for recommendation in recommendations:
            body.append(f"- {recommendation}\n")
    else:
        body.append("No urgent fixes suggested. Network path looks healthy.")
    return Panel(body, title="Doctor Summary")
