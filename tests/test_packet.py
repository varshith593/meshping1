from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult, ProbeType
from meshping.protocol.packet import (
    decode_discovery_response,
    decode_probe_packet,
    decode_probe_reply,
    decode_result_report,
    encode_discovery_response,
    encode_probe_packet,
    encode_probe_reply,
    encode_result_report,
)


def test_probe_packet_round_trip() -> None:
    data = encode_probe_packet(7, 123456789, 42)
    packet = decode_probe_packet(data)
    assert packet.sequence == 7
    assert packet.timestamp_ns == 123456789
    assert packet.node_id_hash == 42


def test_probe_reply_round_trip() -> None:
    packet = decode_probe_packet(encode_probe_packet(3, 999, 12))
    reply_data = encode_probe_reply(packet, 5000)
    reply = decode_probe_reply(reply_data)
    assert reply.sequence == 3
    assert reply.timestamp_ns == 999
    assert reply.node_id_hash == 12
    assert reply.receive_timestamp_ns == 5000


def test_discovery_response_round_trip() -> None:
    node = Node(id="web1", host="10.0.0.11", port=7777, name="web1", agent=True)
    response = encode_discovery_response(node)
    decoded = decode_discovery_response(response)
    assert decoded.id == "web1"
    assert decoded.host == "10.0.0.11"
    assert decoded.port == 7777


def test_result_report_round_trip() -> None:
    result = ProbeResult(
        source_id="a",
        target_id="b",
        sequence=1,
        sent_at=1,
        received_at=2,
        rtt_ms=1.5,
        success=True,
        error=None,
        probe_type=ProbeType.UDP,
    )
    encoded = encode_result_report(result)
    decoded = decode_result_report(encoded)
    assert decoded == result
