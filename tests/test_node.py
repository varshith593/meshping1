from meshping.models.node import Node


def test_named_cli_target_uses_name_as_id_and_display_name() -> None:
    node = Node.from_target("web1=10.0.0.11:7777", agent=True)

    assert node.id == "web1"
    assert node.name == "web1"
    assert node.host == "10.0.0.11"
    assert node.port == 7777
    assert node.agent is True


def test_unnamed_cli_target_uses_address_as_id() -> None:
    node = Node.from_target("10.0.0.11:7777")

    assert node.id == "10.0.0.11:7777"
    assert node.name == "10.0.0.11"
