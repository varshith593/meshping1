from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class StressStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADING = "DEGRADING"
    BREAKING = "BREAKING"


class StressResult(BaseModel):
    load_level_pps: int = Field(ge=0)
    requested_pps: int | None = Field(default=None, ge=0)
    achieved_pps: float | None = Field(default=None, ge=0)
    degradation_pct: float | None = None
    avg_rtt: float | None = None
    p50_rtt: float | None = None
    p99_rtt: float | None = None
    loss_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    status: StressStatus = StressStatus.HEALTHY
    attempted: int = Field(default=0, ge=0)
    succeeded: int = Field(default=0, ge=0)
    refused: int = Field(default=0, ge=0)
    timed_out: int = Field(default=0, ge=0)
    max_rtt: float | None = None
    protocol: str = "tcp"
    target: str | None = None
    sparkline: str | None = None
    bufferbloat_detected: bool = False
    nic_saturated_at: int | None = Field(default=None, ge=0)
    note: str | None = None
