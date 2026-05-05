from __future__ import annotations

from collections import deque

from pydantic import BaseModel, ConfigDict, Field


class MatrixCell(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    source_id: str
    target_id: str
    samples: deque[float | None] = Field(default_factory=lambda: deque(maxlen=100))
    history: deque[tuple[float, float | None]] = Field(
        default_factory=lambda: deque(maxlen=300)
    )
    p50: float | None = None
    p99: float | None = None
    min_rtt: float | None = None
    max_rtt: float | None = None
    loss_pct: float = 0.0
    jitter_ms: float | None = None
    last_updated: int | None = None
    baseline_p50: float | None = None
    rolling_5min_p50: float | None = None
    route_change_fired: bool = False
    route_change_checks: int = 0
    last_route_change_check_at: float | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    total_probes: int = 0
    successful_probes: int = 0
    asymmetric: bool = False
    asymmetry_ratio: float | None = None
    ipv4_rtt_ms: float | None = None
    ipv6_rtt_ms: float | None = None
    preferred_ip_version: str | None = None
    protocol_race_note: str | None = None
    stability_pct: int | None = None
