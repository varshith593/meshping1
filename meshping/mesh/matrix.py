from __future__ import annotations

import math
import statistics
from collections import deque
from typing import Iterable

from meshping.models.matrix_cell import MatrixCell
from meshping.models.probe_result import ProbeResult


def _percentile(samples: list[float], pct: float) -> float | None:
    if not samples:
        return None
    if len(samples) == 1:
        return samples[0]
    if pct == 0.50:
        return float(statistics.median(samples))
    ordered = sorted(samples)
    index = min(max(math.ceil(len(ordered) * pct) - 1, 0), len(ordered) - 1)
    return ordered[index]


def _jitter(samples: list[float]) -> float | None:
    if len(samples) < 2:
        return None
    deltas = [abs(curr - prev) for prev, curr in zip(samples, samples[1:], strict=False)]
    return statistics.fmean(deltas) if deltas else None


class MatrixStore:
    def __init__(self, *, history_window: int = 100) -> None:
        self.history_window = history_window
        self.cells: dict[tuple[str, str], MatrixCell] = {}

    def ensure_cell(self, source_id: str, target_id: str) -> MatrixCell:
        key = (source_id, target_id)
        if key not in self.cells:
            self.cells[key] = MatrixCell(
                source_id=source_id,
                target_id=target_id,
                samples=deque(maxlen=self.history_window),
                history=deque(maxlen=max(self.history_window * 3, 300)),
            )
        return self.cells[key]

    def update(self, result: ProbeResult) -> MatrixCell:
        cell = self.ensure_cell(result.source_id, result.target_id)
        cell.total_probes += 1
        cell.last_updated = result.received_at or result.sent_at
        cell.last_error = result.error
        event_ts = (result.received_at or result.sent_at) / 1_000_000_000
        cell.history.append((event_ts, result.rtt_ms if result.success else None))

        if result.success and result.rtt_ms is not None:
            cell.samples.append(result.rtt_ms)
            cell.successful_probes += 1
            cell.consecutive_failures = 0
        else:
            cell.samples.append(None)
            cell.consecutive_failures += 1

        valid_samples = [sample for sample in cell.samples if sample is not None]
        if valid_samples:
            cell.p50 = _percentile(valid_samples, 0.50)
            cell.p99 = _percentile(valid_samples, 0.99)
            cell.min_rtt = min(valid_samples)
            cell.max_rtt = max(valid_samples)
            cell.jitter_ms = _jitter(valid_samples)
            if cell.baseline_p50 is None and len(valid_samples) >= 10:
                cell.baseline_p50 = statistics.fmean(valid_samples[:10])
            recent_samples = [
                sample
                for sample_ts, sample in cell.history
                if sample is not None and sample_ts >= event_ts - 300
            ]
            cell.rolling_5min_p50 = _percentile(recent_samples, 0.50)
        else:
            cell.p50 = None
            cell.p99 = None
            cell.min_rtt = None
            cell.max_rtt = None
            cell.jitter_ms = None
            cell.rolling_5min_p50 = None

        total = len(cell.samples)
        lost = sum(1 for sample in cell.samples if sample is None)
        cell.loss_pct = (lost / total) * 100 if total else 0.0
        if result.ipv4_rtt_ms is not None:
            cell.ipv4_rtt_ms = result.ipv4_rtt_ms
        elif result.ip_version == "IPv4" and result.rtt_ms is not None:
            cell.ipv4_rtt_ms = result.rtt_ms
        if result.ipv6_rtt_ms is not None:
            cell.ipv6_rtt_ms = result.ipv6_rtt_ms
        elif result.ip_version == "IPv6" and result.rtt_ms is not None:
            cell.ipv6_rtt_ms = result.rtt_ms
        cell.preferred_ip_version = _preferred_ip_version(cell)
        cell.protocol_race_note = _protocol_race_note(cell)
        cell.stability_pct = _stability_pct(cell)
        return cell

    def get(self, source_id: str, target_id: str) -> MatrixCell | None:
        return self.cells.get((source_id, target_id))

    def iter_cells(self) -> Iterable[MatrixCell]:
        return self.cells.values()

def _preferred_ip_version(cell: MatrixCell) -> str | None:
    if cell.ipv4_rtt_ms is not None and cell.ipv6_rtt_ms is not None:
        return "IPv4" if cell.ipv4_rtt_ms <= cell.ipv6_rtt_ms else "IPv6"
    if cell.ipv4_rtt_ms is not None:
        return "IPv4"
    if cell.ipv6_rtt_ms is not None:
        return "IPv6"
    return None


def _protocol_race_note(cell: MatrixCell) -> str | None:
    if cell.ipv4_rtt_ms is None or cell.ipv6_rtt_ms is None:
        return None
    gap = abs(cell.ipv4_rtt_ms - cell.ipv6_rtt_ms)
    if gap < 5.0:
        return "IPv4/IPv6 balanced"
    if cell.ipv6_rtt_ms > cell.ipv4_rtt_ms:
        return "IPv6 slower than IPv4"
    return "IPv4 slower than IPv6"


def _stability_pct(cell: MatrixCell) -> int:
    jitter_penalty = min((cell.jitter_ms or 0.0) * 2.5, 30.0)
    loss_penalty = min(cell.loss_pct * 6.0, 60.0)
    tail_penalty = 0.0
    if cell.p50 and cell.p99 and cell.p50 > 0:
        tail_penalty = min(((cell.p99 - cell.p50) / cell.p50) * 8.0, 20.0)
    score = 100.0 - jitter_penalty - loss_penalty - tail_penalty
    return max(0, min(100, round(score)))
