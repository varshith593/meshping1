from __future__ import annotations

from pydantic import BaseModel, Field


class Settings(BaseModel):
    probe_interval_s: float = Field(default=1.0, gt=0)
    probe_timeout_s: float = Field(default=2.0, gt=0)
    history_window: int = Field(default=100, ge=10)
    usage_profile: str = Field(default="work")
    anomaly_spike_factor: float = Field(default=3.0, ge=1.0)
    anomaly_loss_pct: float = Field(default=5.0, ge=0.0, le=100.0)
    agent_port: int = Field(default=7777, ge=1, le=65535)
    refresh_rate_s: float = Field(default=1.0, gt=0)
    dns_cache_ttl_s: int = Field(default=60, ge=1)
    cluster_threshold_ms: float = Field(default=5.0, gt=0)
    cluster_recompute_s: float = Field(default=60.0, gt=0)
    asymmetry_threshold: float = Field(default=2.0, gt=1.0)
    route_change_factor: float = Field(default=3.0, gt=1.0)
    route_change_persist_minutes: int = Field(default=5, ge=1)
    route_change_reset_factor: float = Field(default=1.5, gt=1.0)
    route_change_check_s: float = Field(default=60.0, gt=0)
    loopback_alert_ms: float = Field(default=0.5, gt=0)
    split_brain_enabled: bool = True
    protocol_race_enabled: bool = True
