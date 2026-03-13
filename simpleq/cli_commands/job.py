"""Job CLI commands."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING, Annotated, Any, cast

import typer

from simpleq.cli_commands import shared
from simpleq.task import TaskHandle

if TYPE_CHECKING:
    from simpleq.protocols import TaskAppProtocol


def job_enqueue(
    task_name: str,
    queue: Annotated[str | None, typer.Option("--queue", "-q")] = None,
    imports: Annotated[list[str] | None, typer.Option("--import-module")] = None,
    args_json: Annotated[str | None, typer.Option("--args-json")] = None,
    kwargs_json: Annotated[str | None, typer.Option("--kwargs-json")] = None,
    payload_json: Annotated[str | None, typer.Option("--payload-json")] = None,
    delay_seconds: Annotated[int, typer.Option("--delay-seconds")] = 0,
    message_group_id: Annotated[str | None, typer.Option("--message-group-id")] = None,
    deduplication_id: Annotated[str | None, typer.Option("--deduplication-id")] = None,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Enqueue a task invocation from the CLI."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    shared.load_registered_tasks(simpleq, imports or [])
    args, kwargs = shared.parse_invocation_payload(
        args_json=args_json,
        kwargs_json=kwargs_json,
        payload_json=payload_json,
    )
    definition = simpleq.registry.get(task_name)
    if queue is not None:
        definition = replace(definition, queue_ref=queue)
    handle: TaskHandle[Any, Any] = TaskHandle(
        cast("TaskAppProtocol", simpleq),
        definition,
    )
    job = handle.delay_sync(
        *args,
        delay_seconds=delay_seconds,
        message_group_id=message_group_id,
        deduplication_id=deduplication_id,
        **kwargs,
    )
    typer.echo(json.dumps(job.to_payload(), default=str, sort_keys=True))


def register_commands(job_app: typer.Typer) -> None:
    """Register job commands."""
    job_app.command("enqueue")(job_enqueue)
