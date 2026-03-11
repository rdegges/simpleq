"""Direct unit tests for CLI command functions."""

from __future__ import annotations

import asyncio
import json
import sys
from types import ModuleType
from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner

from simpleq import SimpleQ
from simpleq.cli import (
    app,
    collect_dlq_jobs,
    cost_report,
    dashboard_serve,
    dlq_list,
    dlq_redrive,
    doctor,
    import_modules,
    init_project,
    job_enqueue,
    main,
    make_client,
    metrics_serve,
    parse_invocation_payload,
    queue_create,
    queue_delete,
    queue_purge,
    queue_stats,
    run_reloading_worker,
    task_list,
    worker_start,
)
from simpleq.config import SimpleQConfig
from simpleq.queue import QueueStats
from simpleq.task import task_name_for
from simpleq.testing import InMemoryTransport
from tests.fixtures.tasks import record_sync

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


class FakeJob:
    def to_payload(self) -> dict[str, str]:
        return {"task_name": "fake"}


class FakeQueue:
    def __init__(self, name: str = "emails") -> None:
        self.name = name
        self.ensure_called = False
        self.deleted = False
        self.purged = False
        self.redriven = False

    def ensure_exists_sync(self) -> str:
        self.ensure_called = True
        return self.name

    def delete_sync(self) -> None:
        self.deleted = True

    async def purge(self) -> None:
        self.purged = True

    def stats_sync(self) -> QueueStats:
        return QueueStats(
            self.name,
            False,
            f"{self.name}-dlq",
            1,
            0,
            0,
            2,
            0,
            0,
        )

    async def get_dlq_jobs(self, *, limit: int) -> object:
        for _ in range(limit):
            yield FakeJob()
            break

    async def redrive_dlq_jobs(self, *, limit: int | None = None) -> int:
        self.redriven = True
        return 2 if limit is None else limit


class FakeWorker:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def work_sync(self, *, burst: bool = False) -> None:
        self.calls.append(burst)


class FakeCostTracker:
    def total_cost(self) -> float:
        return 1.25

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {"emails": {"total_requests": 3}}


class FakeMetrics:
    registry = object()


class FakeClient:
    def __init__(self) -> None:
        self.queue_instance = FakeQueue()
        self.worker_instance = FakeWorker()
        self.cost_tracker = FakeCostTracker()
        self.metrics = FakeMetrics()
        self.config = SimpleQConfig(endpoint_url="http://localhost:4566")
        self.registry = type(
            "Registry",
            (),
            {"names": lambda self: ["tests.fixtures.tasks:record_sync"]},
        )()
        self.worker_calls: list[dict[str, object]] = []

    def queue(self, name: str, **kwargs: object) -> FakeQueue:
        self.queue_instance.name = name
        return self.queue_instance

    def worker(
        self, *, queues: list[str], concurrency: int | None = None
    ) -> FakeWorker:
        assert queues
        self.worker_calls.append({"queues": list(queues), "concurrency": concurrency})
        return self.worker_instance

    def run_sync(self, awaitable: object) -> object:
        return asyncio.run(awaitable) if asyncio.iscoroutine(awaitable) else awaitable


def test_make_client(monkeypatch: pytest.MonkeyPatch) -> None:
    created = {}

    class StubSimpleQ:
        def __init__(
            self, *, endpoint_url: str | None = None, region: str | None = None
        ) -> None:
            created["endpoint_url"] = endpoint_url
            created["region"] = region

    monkeypatch.setattr("simpleq.cli.SimpleQ", StubSimpleQ)
    make_client(endpoint_url="http://localhost:4566", region="us-east-1")
    assert created == {"endpoint_url": "http://localhost:4566", "region": "us-east-1"}


def test_import_modules_and_main(monkeypatch: pytest.MonkeyPatch) -> None:
    imported: list[str] = []
    monkeypatch.setattr("simpleq.cli.importlib.import_module", imported.append)
    import_modules(["tests.fixtures.tasks"])
    assert imported == ["tests.fixtures.tasks"]

    called = {"value": False}
    monkeypatch.setattr("simpleq.cli.app", lambda: called.__setitem__("value", True))
    main()
    assert called["value"] is True


def test_worker_start_and_queue_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeClient()
    monkeypatch.setattr("simpleq.cli.make_client", lambda **_: client)
    monkeypatch.setattr(
        "simpleq.cli.import_modules", lambda modules, reload=False: modules
    )

    with pytest.raises(typer.BadParameter):
        worker_start(queues=[], imports=[], concurrency=7, burst=False)

    worker_start(
        queues=["emails"], imports=["tests.fixtures.tasks"], concurrency=7, burst=True
    )
    assert client.worker_instance.calls == [True]
    assert client.worker_calls[0]["concurrency"] == 7

    worker_start(
        queues=["emails"],
        imports=["tests.fixtures.tasks"],
        burst=True,
    )
    assert client.worker_calls[1]["concurrency"] is None

    reload_calls: dict[str, object] = {}
    monkeypatch.setattr(
        "simpleq.cli.run_reloading_worker",
        lambda **kwargs: reload_calls.update(kwargs),
    )
    worker_start(
        queues=["emails"],
        imports=["tests.fixtures.tasks"],
        concurrency=7,
        burst=False,
        reload=True,
    )
    assert reload_calls["queues"] == ["emails"]

    queue_create("emails")
    queue_delete("emails")
    queue_purge("emails")
    queue_stats("emails")
    captured = capsys.readouterr().out
    assert "emails" in captured
    assert client.queue_instance.ensure_called is True
    assert client.queue_instance.deleted is True
    assert client.queue_instance.purged is True


def test_dlq_cost_metrics_and_dashboard_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeClient()
    monkeypatch.setattr("simpleq.cli.make_client", lambda **_: client)

    dlq_list("emails", limit=1)
    dlq_redrive("emails", limit=3)
    cost_report()
    output = capsys.readouterr().out
    assert '"task_name": "fake"' in output
    assert "\n3\n" in output
    assert json.loads(output.splitlines()[-1])["total_cost"] == 1.25

    jobs = asyncio.run(collect_dlq_jobs(client.queue_instance, limit=1))
    assert len(jobs) == 1

    metrics_calls = {}
    monkeypatch.setattr(
        "simpleq.cli.start_http_server",
        lambda port, addr, registry: metrics_calls.update(
            {"port": port, "addr": addr, "registry": registry}
        ),
    )
    monkeypatch.setattr(
        "simpleq.cli.time.sleep",
        lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        metrics_serve(host="0.0.0.0", port=9100)
    assert metrics_calls["port"] == 9100

    class FakeServer:
        def __init__(self) -> None:
            self.called = False

        def serve_forever(self) -> None:
            self.called = True

    fake_server = FakeServer()
    monkeypatch.setattr(
        "simpleq.cli.create_dashboard_server", lambda *args, **kwargs: fake_server
    )
    dashboard_serve(host="0.0.0.0", port=8081, queue_names=["emails"])
    assert fake_server.called is True


def test_dlq_list_rejects_non_positive_limit_via_cli() -> None:
    result = runner.invoke(app, ["dlq", "list", "emails", "--limit", "0"])

    assert result.exit_code == 2
    assert "Invalid value for '--limit'" in result.output


def test_dlq_redrive_rejects_non_positive_limit_via_cli() -> None:
    result = runner.invoke(app, ["dlq", "redrive", "emails", "--limit", "0"])

    assert result.exit_code == 2
    assert "Invalid value for '--limit'" in result.output


def test_queue_stats_command_includes_dlq_depth(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeClient()
    monkeypatch.setattr("simpleq.cli.make_client", lambda **_: client)

    queue_stats("emails")

    payload = json.loads(capsys.readouterr().out)
    assert payload["available_messages"] == 1
    assert payload["dlq_available_messages"] == 2


def test_doctor_and_task_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeClient()
    monkeypatch.setattr("simpleq.cli.make_client", lambda **_: client)

    doctor(check_sqs=False)
    task_list(imports=["tests.fixtures.tasks"])
    output_lines = capsys.readouterr().out.splitlines()
    doctor_payload = json.loads(output_lines[0])
    assert doctor_payload["config"]["endpoint_url"] == "http://localhost:4566"
    assert json.loads(output_lines[1]) == ["tests.fixtures.tasks:record_sync"]


def test_job_enqueue_uses_registered_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    simpleq.task(queue="emails")(record_sync)
    monkeypatch.setattr("simpleq.cli.make_client", lambda **_: simpleq)
    monkeypatch.setattr(
        "simpleq.cli.import_modules", lambda modules, reload=False: modules
    )

    job_enqueue(task_name_for(record_sync), payload_json='["hello"]')

    received = simpleq.run_sync(
        simpleq.queue("emails").receive(max_messages=1, wait_seconds=0)
    )
    assert len(received) == 1
    assert received[0].args == ("hello",)


def test_job_enqueue_rebinds_imported_queue_handles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("tests.dynamic_cli_imports")
    source = SimpleQ(transport=InMemoryTransport())
    source_queue = source.queue(
        "emails",
        dlq=True,
        wait_seconds=0,
        visibility_timeout=4,
    )
    module.handle = source.task(queue=source_queue)(record_sync)
    sys.modules[module.__name__] = module
    try:
        target = SimpleQ(transport=InMemoryTransport())
        monkeypatch.setattr("simpleq.cli.make_client", lambda **_: target)

        job_enqueue(
            task_name_for(record_sync),
            imports=[module.__name__],
            payload_json='["hello"]',
        )

        target_received = target.run_sync(
            target.resolve_queue("emails").receive(
                max_messages=1,
                wait_seconds=0,
            )
        )
        source_received = source.run_sync(
            source_queue.receive(max_messages=1, wait_seconds=0)
        )

        assert len(target_received) == 1
        assert target_received[0].args == ("hello",)
        assert source_received == []
    finally:
        sys.modules.pop(module.__name__, None)


def test_init_project_creates_scaffold(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    init_project(target=target)
    assert (target / "simpleq_app.py").exists()
    assert (target / ".env.example").exists()


def test_run_reloading_worker_rejects_missing_imports() -> None:
    with pytest.raises(typer.BadParameter):
        run_reloading_worker(
            queues=["emails"],
            imports=[],
            concurrency=1,
            burst=False,
            endpoint_url=None,
            region=None,
        )


@pytest.mark.parametrize(
    ("kwargs", "expected_message"),
    [
        ({"args_json": "["}, "--args-json must contain valid JSON."),
        ({"kwargs_json": "{"}, "--kwargs-json must contain valid JSON."),
        ({"payload_json": "{"}, "--payload-json must contain valid JSON."),
    ],
)
def test_parse_invocation_payload_rejects_invalid_json(
    kwargs: dict[str, str],
    expected_message: str,
) -> None:
    with pytest.raises(typer.BadParameter, match=expected_message):
        parse_invocation_payload(**kwargs)
