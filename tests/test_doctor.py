from meshping.local.doctor import DoctorStatus, check_loopback, check_split_brain
from meshping.models.probe_result import ProbeResult, ProbeType


async def test_check_loopback_warns_when_local_stack_is_slow(monkeypatch) -> None:
    async def fake_probe_loopback(*, timeout: float, sequence: int = 1) -> ProbeResult:
        return ProbeResult(
            source_id="local",
            target_id="localhost",
            sequence=sequence,
            sent_at=1,
            received_at=2,
            rtt_ms=1.2,
            success=True,
            probe_type=ProbeType.TCP,
        )

    monkeypatch.setattr("meshping.local.doctor.probe_loopback", fake_probe_loopback)

    check = await check_loopback(timeout=1.0)

    assert check.status == DoctorStatus.WARN
    assert "elevated" in check.explanation


async def test_check_split_brain_blames_wifi_when_gateway_is_slow(monkeypatch) -> None:
    async def fake_probe_icmp(node, *, source_id: str, timeout: float, sequence: int):
        rtt_ms = 25.0 if node.host != "8.8.8.8" else 30.0
        return ProbeResult(
            source_id=source_id,
            target_id=node.id,
            sequence=sequence,
            sent_at=1,
            received_at=2,
            rtt_ms=rtt_ms,
            success=True,
            probe_type=ProbeType.ICMP,
        )

    monkeypatch.setattr("meshping.local.doctor.default_gateway", lambda: "192.168.1.1")
    monkeypatch.setattr("meshping.local.doctor.probe_icmp", fake_probe_icmp)

    check = await check_split_brain(timeout=1.0)

    assert check.status == DoctorStatus.WARN
    assert check.explanation == "WiFi interference"
