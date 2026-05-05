import asyncio
import contextlib
import socket

from meshping.agent.server import MeshpingAgent, discover_agents
from meshping.config.settings import Settings
from meshping.mesh.coordinator import Coordinator
from meshping.models.node import Node
from meshping.prober.agent_probe import probe_agent


def free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def test_agent_probe_and_discovery() -> None:
    port = free_udp_port()
    agent = MeshpingAgent(
        local_node=Node(id="agent1", name="agent1", host="127.0.0.1", port=port, agent=True),
        settings=Settings(agent_port=port, probe_interval_s=0.1),
    )
    task = asyncio.create_task(agent.run_forever())
    try:
        await asyncio.sleep(0.1)
        target = Node(id="agent1", name="agent1", host="127.0.0.1", port=port, agent=True)
        result = await probe_agent(
            target,
            source_id="local",
            timeout=1.0,
            sequence=1,
            node_id_hash=1,
        )
        assert result.success is True
        assert result.rtt_ms is not None

        discovered = await discover_agents("127.0.0.1/32", port=port, timeout=0.2)
        assert any(node.id == "agent1" for node in discovered)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_distributed_agents_report_full_mesh_to_coordinator() -> None:
    port_a = free_udp_port()
    port_b = free_udp_port()
    coordinator_port = free_udp_port()

    settings = Settings(probe_interval_s=0.05, probe_timeout_s=0.2)
    agent_a = MeshpingAgent(
        local_node=Node(id="a", name="a", host="127.0.0.1", port=port_a, agent=True),
        settings=settings.model_copy(),
    )
    agent_b = MeshpingAgent(
        local_node=Node(id="b", name="b", host="127.0.0.1", port=port_b, agent=True),
        settings=settings.model_copy(),
    )
    agent_tasks = [
        asyncio.create_task(agent_a.run_forever()),
        asyncio.create_task(agent_b.run_forever()),
    ]

    coordinator = Coordinator(
        nodes=[
            Node.from_target(f"a=127.0.0.1:{port_a}", agent=True),
            Node.from_target(f"b=127.0.0.1:{port_b}", agent=True),
        ],
        settings=settings.model_copy(),
    )
    coordinator_task = asyncio.create_task(
        coordinator.run_distributed(
            listen_host="127.0.0.1",
            listen_port=coordinator_port,
            public_host="127.0.0.1",
            push_config=True,
        )
    )

    try:
        await asyncio.sleep(0.5)
        assert coordinator.matrix.get("a", "b") is not None
        assert coordinator.matrix.get("b", "a") is not None
        assert coordinator.source_order() == ["a", "b"]
        assert coordinator.target_order() == ["a", "b"]
    finally:
        coordinator.stop()
        coordinator_task.cancel()
        for task in agent_tasks:
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await coordinator_task
        for task in agent_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
