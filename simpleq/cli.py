"""Typer-based CLI for SimpleQ."""

from __future__ import annotations

import typer

from simpleq.cli_commands.job import (
    job_enqueue,
)
from simpleq.cli_commands.job import (
    register_commands as register_job_commands,
)
from simpleq.cli_commands.monitoring import (
    cost_report,
    dashboard_serve,
    metrics_serve,
)
from simpleq.cli_commands.monitoring import (
    register_commands as register_monitoring_commands,
)
from simpleq.cli_commands.queue import (
    collect_dlq_jobs,
    dlq_list,
    dlq_redrive,
    queue_create,
    queue_delete,
    queue_list,
    queue_purge,
    queue_stats,
)
from simpleq.cli_commands.queue import (
    register_commands as register_queue_commands,
)
from simpleq.cli_commands.root import (
    doctor,
    init_project,
)
from simpleq.cli_commands.root import (
    register_commands as register_root_commands,
)
from simpleq.cli_commands.shared import (
    import_modules,
    load_registered_tasks,
    make_client,
    module_paths,
    modules_changed,
    parse_invocation_payload,
    rebind_task_definition,
    snapshot_module_mtimes,
)
from simpleq.cli_commands.task import (
    register_commands as register_task_commands,
)
from simpleq.cli_commands.task import (
    task_list,
)
from simpleq.cli_commands.worker import (
    register_commands as register_worker_commands,
)
from simpleq.cli_commands.worker import (
    run_reloading_worker,
    worker_start,
)

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

register_root_commands(app)
register_worker_commands(worker_app)
register_queue_commands(queue_app, dlq_app)
register_monitoring_commands(cost_app, metrics_app, dashboard_app)
register_task_commands(task_app)
register_job_commands(job_app)


def main() -> None:
    """Run the CLI application."""
    app()


__all__ = [
    "app",
    "collect_dlq_jobs",
    "cost_report",
    "dashboard_serve",
    "dlq_list",
    "dlq_redrive",
    "doctor",
    "import_modules",
    "init_project",
    "job_enqueue",
    "load_registered_tasks",
    "main",
    "make_client",
    "metrics_serve",
    "module_paths",
    "modules_changed",
    "parse_invocation_payload",
    "queue_create",
    "queue_delete",
    "queue_list",
    "queue_purge",
    "queue_stats",
    "rebind_task_definition",
    "run_reloading_worker",
    "snapshot_module_mtimes",
    "task_list",
    "worker_start",
]
