from __future__ import annotations

from pydantic import BaseModel, Field


class Cluster(BaseModel):
    id: str
    node_ids: list[str] = Field(default_factory=list)
    color: str

    @property
    def size(self) -> int:
        return len(self.node_ids)
