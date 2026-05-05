from __future__ import annotations

import csv
import sqlite3
from pathlib import Path


class HeatmapStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def query(
        self,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
    ) -> list[dict[str, float | int | str]]:
        where: list[str] = []
        params: list[str] = []
        if source_id:
            where.append("source_id = ?")
            params.append(source_id)
        if target_id:
            where.append("target_id = ?")
            params.append(target_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""
            SELECT source_id, target_id, dow, hour,
                   AVG(rtt_ms) AS avg_rtt_ms,
                   AVG(loss) * 100 AS loss_pct,
                   COUNT(*) AS samples
            FROM probe_log
            {clause}
            GROUP BY source_id, target_id, dow, hour
            ORDER BY source_id, target_id, dow, hour
        """
        if not self.path.exists():
            return []
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(sql, params)]

    def export_csv(
        self,
        output_path: Path,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
    ) -> None:
        rows = self.query(source_id=source_id, target_id=target_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "source_id",
                    "target_id",
                    "dow",
                    "hour",
                    "avg_rtt_ms",
                    "loss_pct",
                    "samples",
                ],
            )
            writer.writeheader()
            writer.writerows(rows)
