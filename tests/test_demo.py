from meshping.demo.stack import demo_agent_nodes, demo_service_nodes, demo_specs, synthetic_latency_ms


def test_demo_nodes_have_eight_services() -> None:
    assert len(demo_specs()) == 8
    assert len(demo_service_nodes()) == 8
    assert len(demo_agent_nodes()) == 8


def test_synthetic_latency_is_symmetric() -> None:
    forward = synthetic_latency_ms("frontend", "postgres", tick=3)
    reverse = synthetic_latency_ms("postgres", "frontend", tick=3)
    assert forward == reverse
    assert forward > 0
