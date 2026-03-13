"""Root-level CLI commands."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import typer

from simpleq import __version__
from simpleq.cli_commands import shared


def doctor(
    check_sqs: Annotated[bool, typer.Option("--check-sqs")] = False,
    endpoint_url: Annotated[str | None, typer.Option("--endpoint-url")] = None,
    region: Annotated[str | None, typer.Option("--region")] = None,
) -> None:
    """Inspect runtime configuration and optional SQS connectivity."""
    simpleq = shared.make_client(endpoint_url=endpoint_url, region=region)
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


def init_project(
    target: Annotated[Path, typer.Argument()] = Path("."),
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Scaffold a starter SimpleQ application."""
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    skipped: list[str] = []
    for name, content in shared.scaffold_files().items():
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


def register_commands(app: typer.Typer) -> None:
    """Register root commands on the main app."""
    app.command("doctor")(doctor)
    app.command("init")(init_project)
