from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult, ProbeType
from meshping.storage.recorder import ProbeRecorder
from meshping.storage.replay import ReplaySession


def test_probe_recorder_writes_replay_file(tmp_path) -> None:
    source = Node(id="local", host="localhost", port=1, name="local")
    target = Node(id="db", host="127.0.0.1", port=5432, name="db")
    replay_path = tmp_path / "session.mpr"
    history_path = tmp_path / "history.db"
    recorder = ProbeRecorder(
        history_path=history_path,
        replay_path=replay_path,
        nodes=[source, target],
    )
    recorder.open()
    recorder.record(
        ProbeResult(
            source_id="local",
            target_id="db",
            sequence=1,
            sent_at=1_000_000_000,
            received_at=1_010_000_000,
            rtt_ms=10.0,
            success=True,
            probe_type=ProbeType.TCP,
        )
    )
    recorder.close()

    session = ReplaySession.from_file(replay_path)

    assert [node.id for node in session.nodes] == ["local", "db"]
    assert len(session.events) == 1
    assert session.events[0].result.rtt_ms == 10.0
