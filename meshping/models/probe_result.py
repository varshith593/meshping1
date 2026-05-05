from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class ProbeType(StrEnum):
    TCP = "TCP"
    UDP = "UDP"
    HTTP = "HTTP"
    ICMP = "ICMP"


class ProbeResult(BaseModel):
    source_id: str
    target_id: str
    sequence: int
    sent_at: int
    received_at: int | None = None
    remote_received_at: int | None = None
    rtt_ms: float | None = None
    success: bool
    error: str | None = None
    probe_type: ProbeType
    ip_version: str | None = None
    ipv4_rtt_ms: float | None = None
    ipv6_rtt_ms: float | None = None
