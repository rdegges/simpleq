"""SimpleQ CLI — worker management, queue operations, and cost tracking."""

from __future__ import annotations

import importlib
import sys
from typing import Any, Optional

import boto3
import typer
from rich.console import Console
from rich.table import Table

from simpleq import __version__
from simpleq.app import SimpleQ
from simpleq.config import Config
from simpleq.worker import Worker

console = Console()
app = typer.Typer(
    name="simpleq",
    help="The Python task queue for AWS.",
    no_args_is_help=True,
)
queue_app = typer.Typer(
    name="queue",
    help="Queue management commands.",
    no_args_is_help=True,
)
app.add_typer(queue_app, name="queue")


def _discover_app(module_path: str) -> SimpleQ:
    """Import a module and find the SimpleQ instance."""
    # Validate module path — must be a valid dotted Python module name
    if "/" in module_path or "\\" in module_path:
        console.print(
            f"[red]✗[/red] Invalid module path '{module_path}'.\n\n"
            f"  Use a dotted Python module name, not a file path.\n"
            f"  Example: simpleq worker -a myapp.tasks"
        )
        raise typer.Exit(1)

    # Add cwd to path so relative imports work
    if "." not in sys.path:
        sys.path.insert(0, ".")

    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as e:
        console.print(
            f"[red]✗[/red] Could not import module '{module_path}'.\n\n"
            f"  {e}\n\n"
            f"  Make sure the module is importable from the current directory."
        )
        raise typer.Exit(1)

    # Find SimpleQ instances in the module
    instances = []
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, SimpleQ):
            instances.append(obj)

    if not instances:
        console.print(
            f"[red]✗[/red] No SimpleQ instance found in '{module_path}'.\n\n"
            f"  Your module should create a SimpleQ instance:\n\n"
            f"    from simpleq import SimpleQ\n"
            f"    sq = SimpleQ()"
        )
        raise typer.Exit(1)

    if len(instances) > 1:
        console.print(
            f"[yellow]![/yellow] Multiple SimpleQ instances found in "
            f"'{module_path}', using the first one."
        )

    return instances[0]


def _get_sqs_client(region: str | None = None) -> Any:
    """Create a boto3 SQS client for direct queue operations."""
    config = Config()
    kwargs: dict[str, Any] = {
        "region_name": region or config.region,
    }
    if config.endpoint_url:
        kwargs["endpoint_url"] = config.endpoint_url
    return boto3.client("sqs", **kwargs)


def _print_banner(sq: SimpleQ, queue_names: list[str]) -> None:
    """Print the worker startup banner per DESIGN.md spec."""
    task_names = [t.fn.__name__ for t in sq.tasks.values()]

    console.print(f"\n[bold]SimpleQ[/bold] v{__version__}")
    console.print(f"  Region:  {sq.config.region}")
    console.print(f"  Queues:  {', '.join(queue_names)}")
    console.print(f"  Tasks:   {', '.join(task_names)}")
    console.print(
        "\n  Listening for jobs... ([dim]Ctrl+C to stop[/dim])\n"
    )


# ── Worker Command ───────────────────────────────────────────────


@app.command()
def worker(
    app_module: str = typer.Option(
        ..., "-a", "--app", help="Python module containing the SimpleQ app."
    ),
    queues: Optional[str] = typer.Option(
        None, "-q", "--queues", help="Comma-separated queue names to listen to."
    ),
    concurrency: int = typer.Option(
        10, "-c", "--concurrency", help="Number of concurrent jobs."
    ),
) -> None:
    """Start a worker that processes background jobs."""
    sq = _discover_app(app_module)

    if queues:
        queue_names = [q.strip() for q in queues.split(",")]
    else:
        # Use all queues from registered tasks
        queue_names = list(
            {t.queue_name for t in sq.tasks.values()} or {"default"}
        )

    queue_objects = [sq.queue(name) for name in queue_names]

    _print_banner(sq, queue_names)

    w = Worker(queues=queue_objects, tasks=sq.tasks)
    w.work()


# ── Queue Commands ───────────────────────────────────────────────


@queue_app.command("list")
def queue_list(
    region: Optional[str] = typer.Option(None, "--region", "-r"),
) -> None:
    """List all SQS queues."""
    client = _get_sqs_client(region)
    response = client.list_queues()
    urls = response.get("QueueUrls", [])

    if not urls:
        console.print("[dim]No queues found.[/dim]")
        return

    table = Table(title="SQS Queues")
    table.add_column("Queue Name", style="cyan")
    table.add_column("URL", style="dim")

    for url in urls:
        name = url.rsplit("/", 1)[-1]
        table.add_row(name, url)

    console.print(table)


@queue_app.command("create")
def queue_create(
    name: str = typer.Argument(help="Queue name to create."),
    fifo: bool = typer.Option(False, "--fifo", help="Create a FIFO queue."),
    region: Optional[str] = typer.Option(None, "--region", "-r"),
) -> None:
    """Create an SQS queue."""
    client = _get_sqs_client(region)

    if fifo and not name.endswith(".fifo"):
        name = f"{name}.fifo"

    attrs: dict[str, str] = {}
    if fifo:
        attrs["FifoQueue"] = "true"
        attrs["ContentBasedDeduplication"] = "true"

    kwargs: dict[str, Any] = {"QueueName": name}
    if attrs:
        kwargs["Attributes"] = attrs

    client.create_queue(**kwargs)
    console.print(f"[green]✓[/green] Queue '{name}' created.")


@queue_app.command("stats")
def queue_stats(
    name: str = typer.Argument(help="Queue name."),
    region: Optional[str] = typer.Option(None, "--region", "-r"),
) -> None:
    """Show statistics for a queue."""
    client = _get_sqs_client(region)

    try:
        url = client.get_queue_url(QueueName=name)["QueueUrl"]
    except client.exceptions.QueueDoesNotExist:
        console.print(f"[red]✗[/red] Queue '{name}' not found.")
        raise typer.Exit(1)

    resp = client.get_queue_attributes(
        QueueUrl=url, AttributeNames=["All"]
    )
    attrs = resp["Attributes"]

    table = Table(title=f"Queue: {name}")
    table.add_column("Attribute", style="cyan")
    table.add_column("Value", justify="right")

    table.add_row("Messages Available", attrs.get("ApproximateNumberOfMessages", "0"))
    table.add_row("Messages In Flight", attrs.get("ApproximateNumberOfMessagesNotVisible", "0"))
    table.add_row("Messages Delayed", attrs.get("ApproximateNumberOfMessagesDelayed", "0"))
    table.add_row("Visibility Timeout", f"{attrs.get('VisibilityTimeout', '30')}s")
    table.add_row("Created", attrs.get("CreatedTimestamp", "—"))

    console.print(table)


@queue_app.command("purge")
def queue_purge(
    name: str = typer.Argument(help="Queue name."),
    region: Optional[str] = typer.Option(None, "--region", "-r"),
) -> None:
    """Delete all messages in a queue."""
    client = _get_sqs_client(region)

    try:
        url = client.get_queue_url(QueueName=name)["QueueUrl"]
    except client.exceptions.QueueDoesNotExist:
        console.print(f"[red]✗[/red] Queue '{name}' not found.")
        raise typer.Exit(1)

    client.purge_queue(QueueUrl=url)
    console.print(f"[green]✓[/green] Queue '{name}' purged.")


@queue_app.command("delete")
def queue_delete(
    name: str = typer.Argument(help="Queue name."),
    region: Optional[str] = typer.Option(None, "--region", "-r"),
) -> None:
    """Delete an SQS queue."""
    client = _get_sqs_client(region)

    try:
        url = client.get_queue_url(QueueName=name)["QueueUrl"]
    except client.exceptions.QueueDoesNotExist:
        console.print(f"[red]✗[/red] Queue '{name}' not found.")
        raise typer.Exit(1)

    client.delete_queue(QueueUrl=url)
    console.print(f"[green]✓[/green] Queue '{name}' deleted.")


@queue_app.command("dlq")
def queue_dlq(
    name: str = typer.Argument(help="Source queue name."),
    region: Optional[str] = typer.Option(None, "--region", "-r"),
) -> None:
    """List messages in a queue's dead letter queue."""
    client = _get_sqs_client(region)
    dlq_name = f"{name}-dlq"

    try:
        url = client.get_queue_url(QueueName=dlq_name)["QueueUrl"]
    except client.exceptions.QueueDoesNotExist:
        console.print(
            f"[red]✗[/red] No DLQ found for queue '{name}'.\n\n"
            f"  DLQ name expected: {dlq_name}\n"
            f"  Enable DLQ with: SimpleQ(dead_letter_queue=True)"
        )
        raise typer.Exit(1)

    response = client.receive_message(
        QueueUrl=url,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=0,
    )
    messages = response.get("Messages", [])

    if not messages:
        console.print(f"[dim]No messages in DLQ for '{name}'.[/dim]")
        return

    from simpleq.job import Job

    table = Table(title=f"Dead Letter Queue: {dlq_name}")
    table.add_column("Task", style="cyan")
    table.add_column("Message ID", style="dim")

    for msg in messages:
        try:
            job = Job.deserialize(msg["Body"])
            table.add_row(job.task_name, msg["MessageId"])
        except Exception:
            table.add_row("[red]<unreadable>[/red]", msg["MessageId"])

    console.print(table)
    console.print(f"\n  {len(messages)} message(s) in DLQ.")


@queue_app.command("redrive")
def queue_redrive(
    name: str = typer.Argument(help="Source queue name."),
    region: Optional[str] = typer.Option(None, "--region", "-r"),
) -> None:
    """Move all messages from the DLQ back to the source queue."""
    config = Config()
    if region:
        config.region = region

    from simpleq.cost import CostTracker
    from simpleq.queue import Queue

    queue = Queue(name=name, config=config, cost_tracker=CostTracker())

    try:
        count = queue.redrive_dlq()
    except Exception as e:
        console.print(f"[red]✗[/red] Redrive failed: {e}")
        raise typer.Exit(1)

    console.print(
        f"[green]✓[/green] Redrove {count} message(s) from "
        f"'{name}-dlq' back to '{name}'."
    )


# ── Stats Command ────────────────────────────────────────────────


@app.command()
def stats(
    region: Optional[str] = typer.Option(None, "--region", "-r"),
) -> None:
    """Show cost and usage statistics across all queues."""
    client = _get_sqs_client(region)
    response = client.list_queues()
    urls = response.get("QueueUrls", [])

    if not urls:
        console.print("[dim]No queues found.[/dim]")
        return

    table = Table(title="SimpleQ Stats")
    table.add_column("Queue", style="cyan")
    table.add_column("Messages", justify="right")
    table.add_column("In Flight", justify="right")
    table.add_column("Delayed", justify="right")

    for url in urls:
        name = url.rsplit("/", 1)[-1]
        attrs_resp = client.get_queue_attributes(
            QueueUrl=url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            ],
        )
        attrs = attrs_resp["Attributes"]
        table.add_row(
            name,
            attrs.get("ApproximateNumberOfMessages", "0"),
            attrs.get("ApproximateNumberOfMessagesNotVisible", "0"),
            attrs.get("ApproximateNumberOfMessagesDelayed", "0"),
        )

    console.print(table)
