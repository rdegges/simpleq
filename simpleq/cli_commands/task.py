"""Task CLI commands."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from simpleq.cli_commands import shared


def task_list(
    imports: Annotated[list[str] | None, typer.Option("--import-module")] = None,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """List task names registered by imported modules."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    shared.load_registered_tasks(simpleq, imports or [])
    typer.echo(json.dumps(simpleq.registry.names()))


def register_commands(task_app: typer.Typer) -> None:
    """Register task commands."""
    task_app.command("list")(task_list)
