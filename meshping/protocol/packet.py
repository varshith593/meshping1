from __future__ import annotations

import json
import struct
from typing import Any

from pydantic import BaseModel

from meshping.models.node import Node
from meshping.models.probe_result import ProbeResult

MAGIC = 0x4D455348
PROBE_PACKET_STRUCT = struct.Struct(">IIQI")
PROBE_REPLY_STRUCT = struct.Struct(">IIQIQ")


class ProbePacket(BaseModel):
    sequence: int
    timestamp_ns: int
    node_id_hash: int


class ProbeReply(BaseModel):
    sequence: int
    timestamp_ns: int
    node_id_hash: int
    receive_timestamp_ns: int


def encode_probe_packet(sequence: int, timestamp_ns: int, node_id_hash: int) -> bytes:
    return PROBE_PACKET_STRUCT.pack(MAGIC, sequence, timestamp_ns, node_id_hash)


def decode_probe_packet(data: bytes) -> ProbePacket:
    if len(data) != PROBE_PACKET_STRUCT.size:
        raise ValueError(f"Expected 20-byte packet, got {len(data)} bytes")
    magic, sequence, timestamp_ns, node_id_hash = PROBE_PACKET_STRUCT.unpack(data)
    if magic != MAGIC:
        raise ValueError("Invalid probe magic")
    return ProbePacket(
        sequence=sequence,
        timestamp_ns=timestamp_ns,
        node_id_hash=node_id_hash,
    )


def encode_probe_reply(packet: ProbePacket, receive_timestamp_ns: int) -> bytes:
    return PROBE_REPLY_STRUCT.pack(
        MAGIC,
        packet.sequence,
        packet.timestamp_ns,
        packet.node_id_hash,
        receive_timestamp_ns,
    )


def decode_probe_reply(data: bytes) -> ProbeReply:
    if len(data) != PROBE_REPLY_STRUCT.size:
        raise ValueError(f"Expected 28-byte reply, got {len(data)} bytes")
    magic, sequence, timestamp_ns, node_id_hash, receive_timestamp_ns = (
        PROBE_REPLY_STRUCT.unpack(data)
    )
    if magic != MAGIC:
        raise ValueError("Invalid reply magic")
    return ProbeReply(
        sequence=sequence,
        timestamp_ns=timestamp_ns,
        node_id_hash=node_id_hash,
        receive_timestamp_ns=receive_timestamp_ns,
    )


def encode_discovery_request() -> bytes:
    return b"MSHD"


def encode_discovery_response(node: Node) -> bytes:
    payload = {
        "id": node.id,
        "name": node.name,
        "host": node.host,
        "port": node.port,
    }
    return b"MSHR" + json.dumps(payload, separators=(",", ":")).encode("utf-8")


def decode_discovery_response(data: bytes) -> Node:
    if not data.startswith(b"MSHR"):
        raise ValueError("Invalid discovery response")
    payload = json.loads(data[4:].decode("utf-8"))
    return Node.model_validate(payload | {"agent": True})


def encode_control_message(payload: dict[str, Any]) -> bytes:
    return b"MSHC" + json.dumps(payload, separators=(",", ":")).encode("utf-8")


def decode_control_message(data: bytes) -> dict[str, Any]:
    if not data.startswith(b"MSHC"):
        raise ValueError("Invalid control message")
    return json.loads(data[4:].decode("utf-8"))


def encode_result_report(result: ProbeResult) -> bytes:
    return b"MSHP" + result.model_dump_json().encode("utf-8")


def decode_result_report(data: bytes) -> ProbeResult:
    if not data.startswith(b"MSHP"):
        raise ValueError("Invalid result report")
    return ProbeResult.model_validate_json(data[4:].decode("utf-8"))
