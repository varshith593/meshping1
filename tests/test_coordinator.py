from meshping.config.settings import Settings
from meshping.mesh.coordinator import Coordinator


def test_resolve_public_host_prefers_explicit_listen_host() -> None:
    coordinator = Coordinator(nodes=[], settings=Settings())

    assert (
        coordinator._resolve_public_host(listen_host="127.0.0.1", public_host=None)
        == "127.0.0.1"
    )
    assert (
        coordinator._resolve_public_host(listen_host="localhost", public_host=None)
        == "localhost"
    )


def test_resolve_public_host_prefers_override() -> None:
    coordinator = Coordinator(nodes=[], settings=Settings())

    assert (
        coordinator._resolve_public_host(
            listen_host="127.0.0.1",
            public_host="10.0.0.10",
        )
        == "10.0.0.10"
    )
