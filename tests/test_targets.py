from meshping.cli._common import combine_target_inputs, resolve_natural_language_query
from meshping.targets.naming import apply_auto_names


def test_sandbox_targets_used_when_mesh_has_no_targets() -> None:
    nodes = combine_target_inputs((), None, use_sandbox_defaults=True)

    assert any(node.id == "cloudflare" for node in nodes)
    assert any(node.id == "google" for node in nodes)


def test_natural_language_query_resolves_dns_and_router_targets() -> None:
    nodes = resolve_natural_language_query("check my dns and the router")

    ids = {node.id for node in nodes}
    assert "cloudflare" in ids
    assert "google" in ids


def test_auto_names_local_service_ports() -> None:
    nodes = combine_target_inputs(("127.0.0.1:5432",), None)
    apply_auto_names(nodes)

    assert nodes[0].name == "postgres"
