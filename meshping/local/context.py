from __future__ import annotations

from functools import lru_cache
import json
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkContext:
    isp: str | None = None
    city: str | None = None
    region: str | None = None

    @property
    def summary(self) -> str | None:
        if not self.isp and not self.city:
            return None
        place = ", ".join(part for part in [self.city, self.region] if part)
        if place:
            return f"{self.isp or 'unknown ISP'} in {place}"
        return self.isp


@lru_cache(maxsize=1)
def detect_network_context(timeout: float = 0.75) -> NetworkContext:
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=timeout) as response:
            payload = json.load(response)
    except Exception:
        return NetworkContext()
    return NetworkContext(
        isp=payload.get("org"),
        city=payload.get("city"),
        region=payload.get("region"),
    )
