from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import unquote, urlparse


@dataclass(frozen=True)
class ProxyConfig:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None


def proxy_from_url(proxy_url: str) -> ProxyConfig:
    parsed = urlparse(proxy_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http:// and https:// proxies are supported")
    if not parsed.hostname:
        raise ValueError("proxy URL must include a host")
    port = parsed.port or (443 if parsed.scheme == "https" else 8080)
    return ProxyConfig(
        scheme=parsed.scheme,
        host=parsed.hostname,
        port=port,
        username=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
    )


def proxy_for_target(
    host: str,
    port: int,
    *,
    explicit_proxy_url: str | None = None,
    use_env_proxy: bool = True,
) -> ProxyConfig | None:
    if explicit_proxy_url:
        return proxy_from_url(explicit_proxy_url)
    if not use_env_proxy or should_bypass_proxy(host):
        return None

    env = os.environ
    proxy_url = None
    if port == 443:
        proxy_url = env.get("HTTPS_PROXY") or env.get("https_proxy")
    elif port == 80:
        proxy_url = env.get("HTTP_PROXY") or env.get("http_proxy")

    proxy_url = (
        proxy_url
        or env.get("HTTPS_PROXY")
        or env.get("https_proxy")
        or env.get("HTTP_PROXY")
        or env.get("http_proxy")
        or env.get("ALL_PROXY")
        or env.get("all_proxy")
    )
    if not proxy_url:
        return None
    return proxy_from_url(proxy_url)


def should_bypass_proxy(host: str) -> bool:
    normalized = host.strip().lower().strip("[]")
    if normalized in {"localhost", "::1"} or normalized.endswith(".local"):
        return True

    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    if _matches_no_proxy(normalized, no_proxy):
        return True

    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def _matches_no_proxy(host: str, no_proxy: str) -> bool:
    for raw_entry in no_proxy.split(","):
        entry = raw_entry.strip().lower()
        if not entry:
            continue
        if entry == "*":
            return True
        if entry.startswith(".") and host.endswith(entry):
            return True
        if host == entry or host.endswith(f".{entry}"):
            return True
    return False
