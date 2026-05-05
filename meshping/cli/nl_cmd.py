from __future__ import annotations

from meshping.config.settings import Settings

from ._common import resolve_natural_language_query
from .mesh_cmd import run_mesh_session


def run_natural_language_mesh(query: str) -> None:
    nodes = resolve_natural_language_query(query)
    run_mesh_session(
        nodes,
        settings=Settings(),
        show_local=True,
    )
