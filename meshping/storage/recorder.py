from __future__ import annotations

import datetime as dt
import json
import sqlite3
import struct
import time
from pathlib import Path

from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult

MPR_MAGIC = b"MSHPMPR1"
MPR_HEADER = struct.Struct(">8sIIQ8x")
MPR_RECORD = struct.Struct(">dIIiB")


class ProbeRecorder:
    def __init__(
        self,
        *,
        history_path: Path | None = None,
        replay_path: Path | None = None,
        nodes: list[Node] | None = None,
    ) -> None:
        self.history_path = history_path
        self.replay_path = replay_path
        self.nodes = nodes or []
        self._node_index = {node.id: index for index, node in enumerate(self.nodes)}
        self._replay_handle = None

    def __enter__(self) -> "ProbeRecorder":
        self.open()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def open(self) -> None:
        if self.history_path:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.history_path) as conn:
                _ensure_schema(conn)
        if self.replay_path:
            self.replay_path.parent.mkdir(parents=True, exist_ok=True)
            nodes_json = json.dumps(
                [node.model_dump(mode="json") for node in self.nodes],
                separators=(",", ":"),
            ).encode("utf-8")
            self._replay_handle = self.replay_path.open("wb")
            self._replay_handle.write(
                MPR_HEADER.pack(MPR_MAGIC, 1, len(nodes_json), time.time_ns())
            )
            self._replay_handle.write(nodes_json)

    def close(self) -> None:
        if self._replay_handle:
            self._replay_handle.close()
            self._replay_handle = None

    def record(self, result: ProbeResult) -> None:
        self.record_history(result)
        self.record_replay(result)

    def record_history(self, result: ProbeResult) -> None:
        if not self.history_path:
            return
        ts = (result.received_at or result.sent_at) / 1_000_000_000
        stamp = dt.datetime.fromtimestamp(ts)
        with sqlite3.connect(self.history_path) as conn:
            _ensure_schema(conn)
            conn.execute(
                """
                INSERT INTO probe_log(source_id, target_id, hour, dow, rtt_ms, loss, ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.source_id,
                    result.target_id,
                    stamp.hour,
                    stamp.weekday(),
                    result.rtt_ms,
                    0 if result.success else 1,
                    ts,
                ),
            )

    def record_replay(self, result: ProbeResult) -> None:
        if not self._replay_handle:
            return
        source_index = self._node_index.get(result.source_id)
        target_index = self._node_index.get(result.target_id)
        if source_index is None or target_index is None:
            return
        timestamp_s = (result.received_at or result.sent_at) / 1_000_000_000
        rtt_us = -1 if result.rtt_ms is None else round(result.rtt_ms * 1000)
        self._replay_handle.write(
            MPR_RECORD.pack(
                timestamp_s,
                source_index,
                target_index,
                rtt_us,
                1 if result.success else 0,
            )
        )
        self._replay_handle.flush()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS probe_log (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            hour INTEGER NOT NULL,
            dow INTEGER NOT NULL,
            rtt_ms REAL,
            loss INTEGER NOT NULL,
            ts REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_probe_log_pair_time ON probe_log(source_id, target_id, dow, hour)"
    )
