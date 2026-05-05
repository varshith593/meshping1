from __future__ import annotations

import os
from pathlib import Path

import click

from meshping.models.node import Node
from meshping.targets import apply_auto_names, resolve_query_nodes, sandbox_targets


def parse_nodes_argument(value: str | None, *, agent: bool = False) -> list[Node]:
    if not value:
        return []
    try:
        return apply_auto_names([
            Node.from_target(part, agent=agent)
            for part in value.split(",")
            if part.strip()
        ])
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc


def combine_target_inputs(
    targets: tuple[str, ...],
    nodes_value: str | None,
    *,
    agent: bool = False,
    use_sandbox_defaults: bool = False,
    env_var: str | None = None,
) -> list[Node]:
    try:
        parsed = [
            Node.from_target(target, agent=agent)
            for target in targets
            if target.strip()
        ]
    except ValueError as exc:
        raise click.BadParameter(str(exc)) from exc
    parsed.extend(parse_nodes_argument(nodes_value, agent=agent))
    if not parsed and env_var and os.getenv(env_var):
        parsed.extend(parse_nodes_argument(os.getenv(env_var), agent=agent))
    if not parsed and use_sandbox_defaults and not agent:
        parsed.extend(sandbox_targets())
    apply_auto_names(parsed)
    deduped: dict[str, Node] = {}
    for node in parsed:
        deduped[node.id] = node
    return list(deduped.values())


def resolve_natural_language_query(query: str) -> list[Node]:
    return apply_auto_names(resolve_query_nodes(query))


def parse_listen(value: str) -> tuple[str, int]:
    if ":" not in value:
        raise click.BadParameter("listen must be host:port")
    host, port = value.rsplit(":", 1)
    try:
        port_int = int(port)
    except ValueError as exc:
        raise click.BadParameter("port must be an integer") from exc
    if not 1 <= port_int <= 65535:
        raise click.BadParameter("port must be between 1 and 65535")
    return host, port_int


def ensure_export_path(value: str | None) -> Path | None:
    return Path(value) if value else None


def parse_duration(value: str | float | int) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    raw = value.strip().lower()
    if not raw:
        raise click.BadParameter("duration cannot be empty")
    multiplier = 1.0
    if raw.endswith("ms"):
        multiplier = 0.001
        raw = raw[:-2]
    elif raw.endswith("s"):
        raw = raw[:-1]
    elif raw.endswith("m"):
        multiplier = 60.0
        raw = raw[:-1]
    try:
        duration = float(raw) * multiplier
    except ValueError as exc:
        raise click.BadParameter(f"invalid duration: {value}") from exc
    if duration <= 0:
        raise click.BadParameter("duration must be greater than zero")
    return duration


def parse_load_distribution(values: tuple[str, ...]) -> list[tuple[Node, float]]:
    distribution: list[tuple[Node, float]] = []
    for value in values:
        target, sep, percent_raw = value.rpartition("=")
        if not sep:
            raise click.BadParameter("load must look like host:port=60%")
        if percent_raw.endswith("%"):
            percent_raw = percent_raw[:-1]
        try:
            percent = float(percent_raw)
        except ValueError as exc:
            raise click.BadParameter("load percentage must be numeric") from exc
        distribution.append((Node.from_target(target), percent))
    total = sum(percent for _, percent in distribution)
    if distribution and abs(total - 100.0) > 0.01:
        raise click.BadParameter("load percentages must add up to 100")
    return distribution


def parse_levels(value: str) -> list[int]:
    try:
        levels = [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise click.BadParameter("levels must be comma-separated integers") from exc
    if not levels or any(level <= 0 for level in levels):
        raise click.BadParameter("levels must contain positive integers")
    return levels
