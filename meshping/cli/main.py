from __future__ import annotations

import click
import logging
import structlog

from meshping import __version__

from .agent_cmd import agent_command
from .check_cmd import check_command
from .demo_cmd import demo_command
from .doctor_cmd import doctor_command
from .discover_cmd import discover_command
from .diff_cmd import diff_command
from .mesh_cmd import mesh_command, run_mesh_session
from .nl_cmd import run_natural_language_mesh
from .probe_cmd import probe_command
from .replay_cmd import replay_command
from .top_cmd import top_command
from meshping.targets import sandbox_targets

try:
    import uvloop
except ImportError:  # pragma: no cover
    uvloop = None


@click.group(
    invoke_without_command=True,
    context_settings={
        "ignore_unknown_options": True,
        "allow_extra_args": True,
    },
)
@click.version_option(__version__)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Measure latency across many nodes."""
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
        processors=[structlog.processors.KeyValueRenderer()],
    )
    if uvloop:
        uvloop.install()
    if ctx.invoked_subcommand is None and not ctx.resilient_parsing:
        query = " ".join(ctx.args).strip()
        if query:
            run_natural_language_mesh(query)
            ctx.exit()
        run_mesh_session(sandbox_targets(), show_local=True)
        ctx.exit()


cli.add_command(probe_command)
cli.add_command(mesh_command)
cli.add_command(top_command)
cli.add_command(agent_command)
cli.add_command(check_command)
cli.add_command(discover_command)
cli.add_command(demo_command)
cli.add_command(diff_command)
cli.add_command(doctor_command)
cli.add_command(replay_command)


def main() -> None:
    cli()
