import importlib

from click.testing import CliRunner

from meshping.cli.main import cli


FEATURE_MODULES = [
    "meshping.mesh.cluster",
    "meshping.ui.cluster_view",
    "meshping.mesh.asymmetry",
    "meshping.prober.fingerprint",
    "meshping.storage.heatmap_store",
    "meshping.storage.recorder",
    "meshping.storage.replay",
    "meshping.local.health",
    "meshping.local.loopback",
    "meshping.local.nic",
    "meshping.local.doctor",
    "meshping.targets.sandbox",
    "meshping.targets.natural_language",
    "meshping.local.context",
]


def test_professional_feature_modules_are_importable() -> None:
    for module in FEATURE_MODULES:
        importlib.import_module(module)


def test_cli_exposes_new_feature_commands_and_flags() -> None:
    runner = CliRunner()

    root = runner.invoke(cli, ["--help"])
    assert root.exit_code == 0
    for command in ["doctor", "replay", "top", "diff", "demo", "discover"]:
        assert command in root.output

    mesh = runner.invoke(cli, ["mesh", "--help"])
    assert mesh.exit_code == 0
    for flag in ["--record", "--cluster-threshold", "--asymmetry-threshold", "--log", "--profile"]:
        assert flag in mesh.output
    assert "--budget" not in mesh.output
    assert "--metrics-port" not in mesh.output

    probe = runner.invoke(cli, ["probe", "--help"])
    assert probe.exit_code == 0
    assert "--json-output" not in probe.output

    demo = runner.invoke(cli, ["demo", "--help"])
    assert demo.exit_code == 0
    for flag in ["--profile", "--record", "--log"]:
        assert flag in demo.output

    top = runner.invoke(cli, ["top", "--help"])
    assert top.exit_code == 0
    assert "--profile" in top.output

    discover = runner.invoke(cli, ["discover", "--help"])
    assert discover.exit_code == 0
    assert "--subnet" in discover.output
