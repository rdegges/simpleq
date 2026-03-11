"""Typer-based CLI for SimpleQ."""

from __future__ import annotations

import importlib
import json
import os
import sys
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated, Any

import typer
from prometheus_client import start_http_server

from simpleq import __version__
from simpleq.client import SimpleQ
from simpleq.dashboard import create_dashboard_server
from simpleq.queue import Queue
from simpleq.task import TaskDefinition, TaskHandle

app = typer.Typer(help="SimpleQ command line tools.")
worker_app = typer.Typer(help="Worker commands.")
queue_app = typer.Typer(help="Queue commands.")
dlq_app = typer.Typer(help="Dead letter queue commands.")
cost_app = typer.Typer(help="Cost reporting commands.")
metrics_app = typer.Typer(help="Metrics commands.")
dashboard_app = typer.Typer(help="Dashboard commands.")
task_app = typer.Typer(help="Task commands.")
job_app = typer.Typer(help="Job commands.")

app.add_typer(worker_app, name="worker")
app.add_typer(queue_app, name="queue")
app.add_typer(dlq_app, name="dlq")
app.add_typer(cost_app, name="cost")
app.add_typer(metrics_app, name="metrics")
app.add_typer(dashboard_app, name="dashboard")
app.add_typer(task_app, name="task")
app.add_typer(job_app, name="job")


def main() -> None:
    """Run the CLI application."""
    app()


def make_client(
    *,
    endpoint_url: str | None = None,
    region: str | None = None,
) -> SimpleQ:
    """Build a SimpleQ client for CLI commands."""
    return SimpleQ(endpoint_url=endpoint_url, region=region)


def import_modules(module_names: list[str], *, reload: bool = False) -> None:
    """Import modules that register tasks."""
    for module_name in module_names:
        module = importlib.import_module(module_name)
        if reload:
            importlib.reload(module)


def load_registered_tasks(
    simpleq: SimpleQ, module_names: list[str], *, reload: bool = False
) -> None:
    """Import modules and copy discovered task definitions into ``simpleq``."""
    import_modules(module_names, reload=reload)
    for module_name in module_names:
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for value in vars(module).values():
            if isinstance(value, TaskHandle):
                simpleq.registry.register(
                    rebind_task_definition(simpleq, value.definition)
                )
            elif isinstance(value, SimpleQ):
                for task_name in value.registry.names():
                    simpleq.registry.register(
                        rebind_task_definition(simpleq, value.registry.get(task_name))
                    )


def rebind_task_definition(
    simpleq: SimpleQ, definition: TaskDefinition
) -> TaskDefinition:
    """Rebind an imported task definition onto the target SimpleQ client."""
    queue_ref = definition.queue_ref
    if queue_ref is None:
        return replace(definition, queue_ref=None)
    if isinstance(queue_ref, (Queue, str)):
        return replace(definition, queue_ref=simpleq.resolve_queue(queue_ref))
    return replace(definition, queue_ref=queue_ref)


def module_paths(module_names: list[str]) -> list[Path]:
    """Return file paths for imported modules."""
    paths: list[Path] = []
    for module_name in module_names:
        module = sys.modules.get(module_name)
        module_file = getattr(module, "__file__", None)
        if module_file is not None:
            paths.append(Path(module_file))
    return paths


def snapshot_module_mtimes(paths: list[Path]) -> dict[Path, float]:
    """Snapshot module modification times for auto-reload."""
    return {path: path.stat().st_mtime for path in paths if path.exists()}


def modules_changed(previous: dict[Path, float]) -> bool:
    """Return whether any watched module file changed."""
    for path, old_mtime in previous.items():
        if not path.exists():
            return True
        if path.stat().st_mtime != old_mtime:
            return True
    return False


def parse_invocation_payload(
    *,
    args_json: str | None = None,
    kwargs_json: str | None = None,
    payload_json: str | None = None,
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """Parse CLI JSON into task args and kwargs."""
    provided = [value is not None for value in (args_json, kwargs_json, payload_json)]
    if sum(provided) > 1:
        raise typer.BadParameter(
            "Use only one of --args-json, --kwargs-json, or --payload-json."
        )
    if args_json is not None:
        parsed = json.loads(args_json)
        if not isinstance(parsed, list):
            raise typer.BadParameter("--args-json must decode to a JSON array.")
        return tuple(parsed), {}
    if kwargs_json is not None:
        parsed = json.loads(kwargs_json)
        if not isinstance(parsed, dict):
            raise typer.BadParameter("--kwargs-json must decode to a JSON object.")
        return (), parsed
    if payload_json is not None:
        parsed = json.loads(payload_json)
        if isinstance(parsed, list):
            return tuple(parsed), {}
        if isinstance(parsed, dict):
            return (), parsed
        return (parsed,), {}
    return (), {}


def scaffold_files() -> dict[str, str]:
    """Return files generated by ``simpleq init``."""
    return {
        "simpleq_app.py": '''"""Starter SimpleQ application."""

from __future__ import annotations

from pydantic import BaseModel

from simpleq import SimpleQ

sq = SimpleQ()
queue = sq.queue("emails", dlq=True, wait_seconds=0)


class EmailPayload(BaseModel):
    to: str
    subject: str
    body: str


@sq.task(queue=queue, schema=EmailPayload)
def send_email(payload: EmailPayload) -> None:
    print(f"Sending {payload.subject} to {payload.to}")


def main() -> None:
    send_email.delay_sync(
        to="user@example.com",
        subject="Hello",
        body="SimpleQ is ready.",
    )
    sq.worker(queues=[queue], concurrency=1).work_sync(burst=True)


if __name__ == "__main__":
    main()
''',
        ".env.example": """AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=us-east-1
SIMPLEQ_ENDPOINT_URL=http://localhost:4566
""",
    }


def run_reloading_worker(
    *,
    queues: list[str],
    imports: list[str],
    concurrency: int | None,
    burst: bool,
    endpoint_url: str | None,
    region: str | None,
) -> None:
    """Run a worker and restart it when watched files change."""
    if not imports:
        raise typer.BadParameter(
            "--reload requires at least one --import-module to watch."
        )

    bootstrap = make_client(endpoint_url=endpoint_url, region=region)
    load_registered_tasks(bootstrap, imports)
    watched_paths = module_paths(imports)
    if not watched_paths:
        raise typer.BadParameter("Could not resolve import-module file paths.")

    while True:
        simpleq = make_client(endpoint_url=endpoint_url, region=region)
        load_registered_tasks(simpleq, imports, reload=True)
        worker = simpleq.worker(queues=queues, concurrency=concurrency)
        worker_thread = threading.Thread(
            target=worker.work_sync,
            kwargs={"burst": burst},
            daemon=True,
        )
        worker_thread.start()
        mtimes = snapshot_module_mtimes(watched_paths)
        should_restart = False
        try:
            while worker_thread.is_alive():
                time.sleep(0.5)
                if modules_changed(mtimes):
                    simpleq.run_sync(worker.stop())
                    worker_thread.join()
                    importlib.invalidate_caches()
                    watched_paths = module_paths(imports)
                    should_restart = True
                    typer.echo("Detected code changes, restarting worker...", err=True)
                    break
        except KeyboardInterrupt:
            simpleq.run_sync(worker.stop())
            worker_thread.join()
            raise
        worker_thread.join()
        if burst or not should_restart:
            return


@app.command("doctor")
def doctor(
    check_sqs: Annotated[bool, typer.Option("--check-sqs")] = False,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Inspect runtime configuration and optional SQS connectivity."""
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    payload: dict[str, Any] = {
        "version": __version__,
        "python": sys.version.split()[0],
        "config": asdict(simpleq.config),
        "environment": {
            "aws_access_key_id_set": bool(os.getenv("AWS_ACCESS_KEY_ID")),
            "aws_secret_access_key_set": bool(os.getenv("AWS_SECRET_ACCESS_KEY")),
            "aws_default_region": os.getenv("AWS_DEFAULT_REGION"),
            "localstack_hostname": os.getenv("LOCALSTACK_HOSTNAME"),
            "simpleq_env": os.getenv("SIMPLEQ_ENV"),
        },
    }
    if check_sqs:
        try:
            payload["sqs"] = {
                "ok": True,
                "queue_count": len(simpleq.list_queues_sync()),
            }
        except Exception as exc:  # noqa: BLE001
            payload["sqs"] = {
                "ok": False,
                "error": str(exc),
                "exception_type": type(exc).__name__,
            }
    typer.echo(json.dumps(payload, sort_keys=True))


@app.command("init")
def init_project(
    target: Annotated[Path, typer.Argument()] = Path("."),
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Scaffold a starter SimpleQ application."""
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    skipped: list[str] = []
    for name, content in scaffold_files().items():
        path = target / name
        if path.exists() and not force:
            skipped.append(name)
            continue
        path.write_text(content, encoding="utf-8")
        written.append(name)
    typer.echo(
        json.dumps(
            {
                "target": str(target.resolve()),
                "written": written,
                "skipped": skipped,
            },
            sort_keys=True,
        )
    )


@worker_app.command("start")
def worker_start(
    queues: Annotated[list[str] | None, typer.Option("--queue", "-q")] = None,
    imports: Annotated[list[str] | None, typer.Option("--import-module")] = None,
    concurrency: Annotated[int | None, typer.Option("--concurrency")] = None,
    burst: Annotated[bool, typer.Option("--burst")] = False,
    reload: Annotated[bool, typer.Option("--reload")] = False,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Start a SimpleQ worker."""
    queues = queues or []
    imports = imports or []
    if not queues:
        raise typer.BadParameter("At least one --queue is required.")
    if reload:
        run_reloading_worker(
            queues=queues,
            imports=imports,
            concurrency=concurrency,
            burst=burst,
            endpoint_url=endpoint_url,
            region=region,
        )
        return
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    load_registered_tasks(simpleq, imports)
    worker = simpleq.worker(queues=queues, concurrency=concurrency)
    worker.work_sync(burst=burst)


@queue_app.command("create")
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
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(
        name,
        fifo=fifo,
        dlq=dlq,
        content_based_deduplication=content_based_deduplication,
    )
    queue.ensure_exists_sync()
    typer.echo(queue.name)


@queue_app.command("delete")
def queue_delete(
    name: str,
    fifo: Annotated[bool, typer.Option("--fifo")] = False,
    dlq: Annotated[bool, typer.Option("--dlq")] = False,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Delete a queue."""
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(name, fifo=fifo, dlq=dlq)
    queue.delete_sync()
    typer.echo(queue.name)


@queue_app.command("list")
def queue_list(
    prefix: Annotated[str | None, typer.Option("--prefix")] = None,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """List queues."""
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    typer.echo(json.dumps(sorted(simpleq.list_queues_sync(prefix))))


@queue_app.command("stats")
def queue_stats(
    name: str,
    fifo: Annotated[bool, typer.Option("--fifo")] = False,
    dlq: Annotated[bool, typer.Option("--dlq")] = False,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Show queue stats as JSON."""
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(name, fifo=fifo, dlq=dlq)
    typer.echo(json.dumps(asdict(queue.stats_sync()), sort_keys=True))


@queue_app.command("purge")
def queue_purge(
    name: str,
    fifo: Annotated[bool, typer.Option("--fifo")] = False,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Purge all visible messages from a queue."""
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(name, fifo=fifo)
    simpleq.run_sync(queue.purge())
    typer.echo(queue.name)


@dlq_app.command("list")
def dlq_list(
    name: str,
    fifo: Annotated[bool, typer.Option("--fifo")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 10,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """List DLQ jobs."""
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(name, fifo=fifo, dlq=True)
    jobs = simpleq.run_sync(collect_dlq_jobs(queue, limit=limit))
    typer.echo(json.dumps([job.to_payload() for job in jobs], default=str))


@dlq_app.command("redrive")
def dlq_redrive(
    name: str,
    fifo: Annotated[bool, typer.Option("--fifo")] = False,
    limit: Annotated[int | None, typer.Option("--limit", min=1)] = None,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Move DLQ jobs back to the primary queue."""
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    queue = simpleq.queue(name, fifo=fifo, dlq=True)
    typer.echo(str(simpleq.run_sync(queue.redrive_dlq_jobs(limit=limit))))


@cost_app.command("report")
def cost_report(
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Render the current in-process cost tracker snapshot."""
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    payload = {
        "total_cost": simpleq.cost_tracker.total_cost(),
        "queues": simpleq.cost_tracker.snapshot(),
    }
    typer.echo(json.dumps(payload, sort_keys=True))


@metrics_app.command("serve")
def metrics_serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 9090,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Serve Prometheus metrics."""
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    start_http_server(port, addr=host, registry=simpleq.metrics.registry)
    while True:
        time.sleep(3600)


@dashboard_app.command("serve")
def dashboard_serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8080,
    queue_names: Annotated[list[str] | None, typer.Option("--queue")] = None,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Serve the SimpleQ dashboard."""
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    server = create_dashboard_server(
        simpleq,
        host=host,
        port=port,
        queue_names=queue_names or None,
    )
    server.serve_forever()


@task_app.command("list")
def task_list(
    imports: Annotated[list[str] | None, typer.Option("--import-module")] = None,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """List task names registered by imported modules."""
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    load_registered_tasks(simpleq, imports or [])
    typer.echo(json.dumps(simpleq.registry.names()))


@job_app.command("enqueue")
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
    simpleq = make_client(endpoint_url=endpoint_url, region=region)
    load_registered_tasks(simpleq, imports or [])
    args, kwargs = parse_invocation_payload(
        args_json=args_json,
        kwargs_json=kwargs_json,
        payload_json=payload_json,
    )
    definition = simpleq.registry.get(task_name)
    if queue is not None:
        definition = replace(definition, queue_ref=queue)
    handle: TaskHandle[Any, Any] = TaskHandle(simpleq, definition)
    job = handle.delay_sync(
        *args,
        delay_seconds=delay_seconds,
        message_group_id=message_group_id,
        deduplication_id=deduplication_id,
        **kwargs,
    )
    typer.echo(json.dumps(job.to_payload(), default=str, sort_keys=True))


async def collect_dlq_jobs(queue: Any, *, limit: int) -> list[Any]:
    """Collect DLQ jobs into a list for CLI output."""
    return [job async for job in queue.get_dlq_jobs(limit=limit)]
