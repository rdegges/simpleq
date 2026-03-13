"""Queue and DLQ CLI commands."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated

import typer

from simpleq.cli_commands import shared

if TYPE_CHECKING:
    from simpleq.job import Job
    from simpleq.queue import Queue


def queue_create(
    name: str,
    fifo: Annotated[bool, typer.Option("--fifo")] = False,
    dlq: Annotated[bool, typer.Option("--dlq")] = False,
    content_based_deduplication: Annotated[
        bool, typer.Option("--content-based-deduplication")
    ] = False,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Create a queue."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(
        name,
        fifo=fifo,
        dlq=dlq,
        content_based_deduplication=content_based_deduplication,
    )
    queue.ensure_exists_sync()
    typer.echo(queue.name)


def queue_delete(
    name: str,
    fifo: Annotated[bool, typer.Option("--fifo")] = False,
    dlq: Annotated[bool, typer.Option("--dlq")] = False,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Delete a queue."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(name, fifo=fifo, dlq=dlq)
    queue.delete_sync()
    typer.echo(queue.name)


def queue_list(
    prefix: Annotated[str | None, typer.Option("--prefix")] = None,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """List queues."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    typer.echo(json.dumps(sorted(simpleq.list_queues_sync(prefix))))


def queue_stats(
    name: str,
    fifo: Annotated[bool, typer.Option("--fifo")] = False,
    dlq: Annotated[bool, typer.Option("--dlq")] = False,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Show queue stats as JSON."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(name, fifo=fifo, dlq=dlq)
    typer.echo(json.dumps(asdict(queue.stats_sync()), sort_keys=True))


def queue_purge(
    name: str,
    fifo: Annotated[bool, typer.Option("--fifo")] = False,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Purge all visible messages from a queue."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(name, fifo=fifo)
    simpleq.run_sync(queue.purge())
    typer.echo(queue.name)


async def collect_dlq_jobs(queue: Queue, *, limit: int) -> list[Job]:
    """Collect DLQ jobs into a list for CLI output."""
    return [job async for job in queue.get_dlq_jobs(limit=limit)]


def dlq_list(
    name: str,
    fifo: Annotated[bool, typer.Option("--fifo")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 10,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """List DLQ jobs."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(name, fifo=fifo, dlq=True)
    jobs = simpleq.run_sync(collect_dlq_jobs(queue, limit=limit))
    typer.echo(json.dumps([job.to_payload() for job in jobs], default=str))


def dlq_redrive(
    name: str,
    fifo: Annotated[bool, typer.Option("--fifo")] = False,
    limit: Annotated[int | None, typer.Option("--limit", min=1)] = None,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Move DLQ jobs back to the primary queue."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(name, fifo=fifo, dlq=True)
    typer.echo(str(simpleq.run_sync(queue.redrive_dlq_jobs(limit=limit))))


def register_commands(queue_app: typer.Typer, dlq_app: typer.Typer) -> None:
    """Register queue-related commands."""
    queue_app.command("create")(queue_create)
    queue_app.command("delete")(queue_delete)
    queue_app.command("list")(queue_list)
    queue_app.command("stats")(queue_stats)
    queue_app.command("purge")(queue_purge)
    dlq_app.command("list")(dlq_list)
    dlq_app.command("redrive")(dlq_redrive)
