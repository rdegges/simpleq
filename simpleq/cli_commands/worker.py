"""Worker-related CLI commands."""

from __future__ import annotations

import importlib
import threading
import time
from typing import Annotated

import typer

from simpleq.cli_commands import shared


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

    bootstrap = shared.make_client(endpoint_url=endpoint_url, region=region)
    shared.load_registered_tasks(bootstrap, imports)
    watched_paths = shared.module_paths(imports)
    if not watched_paths:
        raise typer.BadParameter("Could not resolve import-module file paths.")

    while True:
        simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
        shared.load_registered_tasks(simpleq, imports, reload=True)
        worker = simpleq.worker(queues=queues, concurrency=concurrency)
        worker_thread = threading.Thread(
            target=worker.work_sync,
            kwargs={"burst": burst},
            daemon=True,
        )
        worker_thread.start()
        mtimes = shared.snapshot_module_mtimes(watched_paths)
        should_restart = False
        try:
            while worker_thread.is_alive():
                time.sleep(0.5)
                if shared.modules_changed(mtimes):
                    simpleq.run_sync(worker.stop())
                    worker_thread.join()
                    importlib.invalidate_caches()
                    watched_paths = shared.module_paths(imports)
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
    queue_names = list(queues or [])
    imports = imports or []
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    if not queue_names:
        queue_names = [simpleq.config.default_queue_name]
    if reload:
        run_reloading_worker(
            queues=queue_names,
            imports=imports,
            concurrency=concurrency,
            burst=burst,
            endpoint_url=endpoint_url,
            region=region,
        )
        return
    shared.load_registered_tasks(simpleq, imports)
    worker = simpleq.worker(queues=queue_names, concurrency=concurrency)
    worker.work_sync(burst=burst)


def register_commands(worker_app: typer.Typer) -> None:
    """Register worker commands."""
    worker_app.command("start")(worker_start)
