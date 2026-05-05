from __future__ import annotations

import time

from meshping.config.settings import Settings
from meshping.mesh.asymmetry import detect_asymmetries
from meshping.mesh.matrix import MatrixStore
from meshping.models.alert import Alert, AlertType, Severity


class Analyzer:
    def __init__(
        self,
        settings: Settings,
    ) -> None:
        self.settings = settings
        self.active_alerts: dict[tuple[AlertType, str, str], Alert] = {}
        self.recent_recoveries: list[Alert] = []

    def evaluate(self, matrix: MatrixStore) -> list[Alert]:
        now = time.time_ns()
        now_s = now / 1_000_000_000
        self.recent_recoveries.clear()
        seen_keys: set[tuple[AlertType, str, str]] = set()

        for cell in matrix.iter_cells():
            if cell.p50 is not None and cell.baseline_p50:
                multiplier = cell.p50 / cell.baseline_p50 if cell.baseline_p50 else 0
                if multiplier >= self.settings.anomaly_spike_factor:
                    severity = (
                        Severity.CRITICAL
                        if multiplier >= 10.0
                        else Severity.WARNING
                    )
                    self._set_alert(
                        AlertType.SPIKE,
                        cell.source_id,
                        cell.target_id,
                        severity,
                        (
                            f"Latency spike on {cell.source_id}->{cell.target_id}: "
                            f"p50 {cell.p50:.2f}ms vs baseline {cell.baseline_p50:.2f}ms"
                        ),
                        now,
                    )
                    seen_keys.add((AlertType.SPIKE, cell.source_id, cell.target_id))

            if cell.loss_pct >= self.settings.anomaly_loss_pct:
                severity = Severity.CRITICAL if cell.loss_pct >= 50 else Severity.WARNING
                self._set_alert(
                    AlertType.LOSS,
                    cell.source_id,
                    cell.target_id,
                    severity,
                    (
                        f"Loss on {cell.source_id}->{cell.target_id}: "
                        f"{cell.loss_pct:.1f}%"
                    ),
                    now,
                )
                seen_keys.add((AlertType.LOSS, cell.source_id, cell.target_id))

            if cell.consecutive_failures >= 10:
                self._set_alert(
                    AlertType.NODE_DOWN,
                    cell.source_id,
                    cell.target_id,
                    Severity.CRITICAL,
                    f"Node {cell.target_id} appears down from {cell.source_id}",
                    now,
                )
                seen_keys.add((AlertType.NODE_DOWN, cell.source_id, cell.target_id))

            self._check_route_divergence(cell, now, now_s, seen_keys)

        for finding in detect_asymmetries(
            matrix,
            threshold=self.settings.asymmetry_threshold,
        ):
            self._set_alert(
                AlertType.ASYMMETRY,
                finding.source_id,
                finding.target_id,
                Severity.INFO,
                (
                    f"{finding.source_id}->{finding.target_id} is "
                    f"{finding.forward_ms:.2f}ms but {finding.target_id}->"
                    f"{finding.source_id} is {finding.reverse_ms:.2f}ms "
                    f"({finding.ratio:.1f}x asymmetry)"
                ),
                now,
            )
            seen_keys.add((AlertType.ASYMMETRY, finding.source_id, finding.target_id))

        self._resolve_missing(seen_keys, now)
        active = [
            alert for alert in self.active_alerts.values() if alert.resolved_at is None
        ]
        return sorted(active + self.recent_recoveries, key=lambda alert: alert.detected_at)

    def _check_route_divergence(
        self,
        cell,
        now: int,
        now_s: float,
        seen_keys: set[tuple[AlertType, str, str]],
    ) -> None:
        if (
            cell.baseline_p50 is None
            or cell.rolling_5min_p50 is None
            or cell.rolling_5min_p50 <= 0
        ):
            return
        key = (AlertType.ROUTE_CHANGE, cell.source_id, cell.target_id)
        ratio = cell.rolling_5min_p50 / cell.baseline_p50
        last_check = cell.last_route_change_check_at or 0.0
        if now_s - last_check >= self.settings.route_change_check_s:
            cell.last_route_change_check_at = now_s
            if ratio >= self.settings.route_change_factor:
                cell.route_change_checks += 1
            elif not cell.route_change_fired:
                cell.route_change_checks = 0

        if (
            cell.route_change_checks >= self.settings.route_change_persist_minutes
            and not cell.route_change_fired
        ):
            self._set_alert(
                AlertType.ROUTE_CHANGE,
                cell.source_id,
                cell.target_id,
                Severity.WARNING,
                (
                    f"Route change detected on {cell.source_id}->{cell.target_id}: "
                    f"baseline {cell.baseline_p50:.2f}ms -> "
                    f"{cell.rolling_5min_p50:.2f}ms"
                ),
                now,
            )
            cell.route_change_fired = True

        if cell.route_change_fired:
            seen_keys.add(key)

        if cell.route_change_fired and ratio <= self.settings.route_change_reset_factor:
            alert = self.active_alerts.get(key)
            if alert and alert.resolved_at is None:
                alert.resolved_at = now
            self.recent_recoveries.append(
                Alert(
                    alert_id=f"RECOVERY:{cell.source_id}:{cell.target_id}:{now}",
                    source_id=cell.source_id,
                    target_id=cell.target_id,
                    alert_type=AlertType.RECOVERY,
                    severity=Severity.INFO,
                    message=(
                        f"Route change recovery on {cell.source_id}->{cell.target_id}; "
                        f"new baseline {cell.rolling_5min_p50:.2f}ms"
                    ),
                    detected_at=now,
                    resolved_at=now,
                )
            )
            cell.baseline_p50 = cell.rolling_5min_p50
            cell.route_change_fired = False
            cell.route_change_checks = 0
            seen_keys.discard(key)

    def _set_alert(
        self,
        alert_type: AlertType,
        source_id: str,
        target_id: str,
        severity: Severity,
        message: str,
        now: int,
    ) -> None:
        key = (alert_type, source_id, target_id)
        existing = self.active_alerts.get(key)
        if existing and existing.resolved_at is None:
            existing.severity = severity
            existing.message = message
            return
        self.active_alerts[key] = Alert(
            alert_id=f"{alert_type}:{source_id}:{target_id}:{now}",
            source_id=source_id,
            target_id=target_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            detected_at=now,
        )

    def _resolve_missing(
        self, seen_keys: set[tuple[AlertType, str, str]], now: int
    ) -> None:
        for key, alert in list(self.active_alerts.items()):
            if alert.resolved_at is not None or key in seen_keys:
                continue
            alert.resolved_at = now
            if alert.alert_type == AlertType.NODE_DOWN:
                self.recent_recoveries.append(
                    Alert(
                        alert_id=f"RECOVERY:{alert.source_id}:{alert.target_id}:{now}",
                        source_id=alert.source_id,
                        target_id=alert.target_id,
                        alert_type=AlertType.RECOVERY,
                        severity=Severity.INFO,
                        message=(
                            f"Recovery detected for {alert.target_id} from "
                            f"{alert.source_id}"
                        ),
                        detected_at=now,
                        resolved_at=now,
                    )
                )
