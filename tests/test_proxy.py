from meshping.prober.proxy import proxy_for_target, should_bypass_proxy


def test_proxy_for_target_reads_https_proxy(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://user:pass@example-proxy.local:8080")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    proxy = proxy_for_target("github.com", 443)

    assert proxy is not None
    assert proxy.scheme == "http"
    assert proxy.host == "example-proxy.local"
    assert proxy.port == 8080
    assert proxy.username == "user"
    assert proxy.password == "pass"


def test_proxy_for_target_bypasses_loopback_even_when_env_is_set(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://example-proxy.local:8080")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    assert proxy_for_target("127.0.0.1", 443) is None
    assert should_bypass_proxy("localhost") is True


def test_no_proxy_env_bypasses_matching_host(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://example-proxy.local:8080")
    monkeypatch.setenv("NO_PROXY", "github.com,.internal")

    assert proxy_for_target("github.com", 443) is None
    assert proxy_for_target("api.internal", 443) is None


def test_proxy_env_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://example-proxy.local:8080")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    assert proxy_for_target("github.com", 443, use_env_proxy=False) is None
