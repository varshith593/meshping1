from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class AlertType(StrEnum):
    SPIKE = "SPIKE"
    LOSS = "LOSS"
    ASYMMETRY = "ASYMMETRY"
    NODE_DOWN = "NODE_DOWN"
    ROUTE_CHANGE = "ROUTE_CHANGE"
    RECOVERY = "RECOVERY"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class Alert(BaseModel):
    alert_id: str
    source_id: str
    target_id: str
    alert_type: AlertType
    severity: Severity
    message: str
    detected_at: int
    resolved_at: int | None = None
