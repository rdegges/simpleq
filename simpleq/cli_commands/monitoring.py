"""Cost, metrics, and dashboard CLI commands."""

from __future__ import annotations

import json
import time
from typing import Annotated

import typer
from prometheus_client import start_http_server

from simpleq.cli_commands import shared
from simpleq.dashboard import create_dashboard_server


def cost_report(
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Render the current in-process cost tracker snapshot."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    payload = {
        "total_cost": simpleq.cost_tracker.total_cost(),
        "queues": simpleq.cost_tracker.snapshot(),
    }
    typer.echo(json.dumps(payload, sort_keys=True))


def metrics_serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 9090,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Serve Prometheus metrics."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    start_http_server(port, addr=host, registry=simpleq.metrics.registry)
    while True:
        time.sleep(3600)


def dashboard_serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8080,
    queue_names: Annotated[list[str] | None, typer.Option("--queue")] = None,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Serve the SimpleQ dashboard."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
    server = create_dashboard_server(
        simpleq,
        host=host,
        port=port,
        queue_names=queue_names or None,
    )
    server.serve_forever()


def register_commands(
    cost_app: typer.Typer,
    metrics_app: typer.Typer,
    dashboard_app: typer.Typer,
) -> None:
    """Register observability commands."""
    cost_app.command("report")(cost_report)
    metrics_app.command("serve")(metrics_serve)
    dashboard_app.command("serve")(dashboard_serve)
