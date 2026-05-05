from __future__ import annotations

from enum import StrEnum
from hashlib import blake2b
from typing import Self

from pydantic import BaseModel, Field, model_validator


class NodeProtocol(StrEnum):
    TCP = "TCP"
    UDP = "UDP"
    HTTP = "HTTP"
    ICMP = "ICMP"


class Node(BaseModel):
    id: str | None = None
    host: str
    port: int = Field(ge=1, le=65535)
    name: str | None = None
    protocol: NodeProtocol = NodeProtocol.TCP
    agent: bool = False
    resolved_ip: str | None = None
    fingerprint: str | None = None

    @model_validator(mode="after")
    def populate_defaults(self) -> Self:
        if not self.name:
            self.name = self.host
        if not self.id:
            safe_host = self.host.replace(":", "_")
            self.id = f"{safe_host}:{self.port}"
        return self

    @property
    def display_name(self) -> str:
        label = self.name or self.host
        if self.fingerprint:
            return f"{label} [{self.fingerprint}]"
        return label

    @property
    def short_id_hash(self) -> int:
        digest = blake2b(self.id.encode("utf-8"), digest_size=4).digest()
        return int.from_bytes(digest, "big", signed=False)

    @classmethod
    def from_target(cls, value: str, *, agent: bool = False) -> "Node":
        value = value.strip()
        if not value:
            raise ValueError("Empty node target")

        name: str | None = None
        address = value
        if "=" in value:
            name, address = value.split("=", 1)
            name = name.strip() or None

        host, port = cls._split_host_port(address)
        protocol = NodeProtocol.UDP if agent else NodeProtocol.TCP
        return cls(
            id=name,
            host=host,
            port=port,
            name=name,
            protocol=protocol,
            agent=agent,
        )

    @staticmethod
    def _split_host_port(value: str) -> tuple[str, int]:
        value = value.strip()
        if not value:
            raise ValueError("Missing host:port target")
        if value.startswith("["):
            end = value.find("]")
            if end == -1 or end + 2 > len(value):
                raise ValueError(f"Invalid IPv6 target: {value}")
            host = value[1:end]
            port = int(value[end + 2 :])
            return host, port
        if value.count(":") == 1:
            host, port_str = value.rsplit(":", 1)
            return host, int(port_str)
        if value.count(":") > 1:
            raise ValueError(
                "IPv6 targets must use [addr]:port format when passed on the CLI"
            )
        raise ValueError(f"Target must be host:port, got {value}")
