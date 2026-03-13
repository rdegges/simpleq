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
    load_registered_tasks,
    main,
    make_client,
    metrics_serve,
    module_paths,
    modules_changed,
    parse_invocation_payload,
    queue_create,
    queue_delete,
    queue_purge,
    queue_stats,
    rebind_task_definition,
    run_reloading_worker,
    snapshot_module_mtimes,
    task_list,
    worker_start,
)
from simpleq.config import SimpleQConfig
from simpleq.queue import QueueStats
from simpleq.task import TaskDefinition, task_name_for
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

    monkeypatch.setattr("simpleq.cli_commands.shared.SimpleQ", StubSimpleQ)
    make_client(endpoint_url="http://localhost:4566", region="us-east-1")
    assert created == {"endpoint_url": "http://localhost:4566", "region": "us-east-1"}


def test_import_modules_and_main(monkeypatch: pytest.MonkeyPatch) -> None:
    imported: list[str] = []
    monkeypatch.setattr(
        "simpleq.cli_commands.shared.importlib.import_module",
        imported.append,
    )
    import_modules(["tests.fixtures.tasks"])
    assert imported == ["tests.fixtures.tasks"]

    called = {"value": False}
    monkeypatch.setattr("simpleq.cli.app", lambda: called.__setitem__("value", True))
    main()
    assert called["value"] is True


def test_import_modules_reload_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    imported: list[str] = []
    reloaded: list[ModuleType] = []
    module = ModuleType("tests.reload_target")

    def fake_import(module_name: str) -> ModuleType:
        imported.append(module_name)
        return module

    monkeypatch.setattr(
        "simpleq.cli_commands.shared.importlib.import_module", fake_import
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.shared.importlib.reload",
        lambda imported_module: reloaded.append(imported_module) or imported_module,
    )

    import_modules(["tests.reload_target"], reload=True)

    assert imported == ["tests.reload_target"]
    assert reloaded == [module]


def test_load_registered_tasks_rebinds_task_handles_and_simpleq_instances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = SimpleQ(transport=InMemoryTransport())
    source_queue = source.queue(
        "emails",
        dlq=True,
        wait_seconds=0,
        visibility_timeout=4,
    )
    module = ModuleType("tests.dynamic_cli_registry")
    module.handle = source.task(queue=source_queue)(record_sync)
    module.source_simpleq = source
    sys.modules[module.__name__] = module
    try:
        monkeypatch.setattr(
            "simpleq.cli_commands.shared.import_modules",
            lambda module_names, reload=False: None,
        )
        target = SimpleQ(transport=InMemoryTransport())

        load_registered_tasks(target, ["tests.missing_cli_registry", module.__name__])

        definition = target.registry.get(task_name_for(record_sync))
        rebound_queue = target.resolve_queue(definition.queue_ref)
        assert rebound_queue.simpleq is target
        assert rebound_queue.name == "emails"
        assert rebound_queue.dlq is True
        assert rebound_queue.visibility_timeout == 4
    finally:
        sys.modules.pop(module.__name__, None)


def test_rebind_task_definition_handles_none_and_queue_refs() -> None:
    target = SimpleQ(transport=InMemoryTransport())

    unbound = TaskDefinition(
        name="tests.fixtures.tasks:record_sync",
        func=record_sync,
        queue_ref=None,
    )
    assert rebind_task_definition(target, unbound).queue_ref is None

    definition = TaskDefinition(
        name="tests.fixtures.tasks:record_sync",
        func=record_sync,
        queue_ref="emails",
    )
    rebound = rebind_task_definition(target, definition)
    assert target.resolve_queue(rebound.queue_ref).name == "emails"


def test_module_file_helpers_detect_changes(tmp_path: Path) -> None:
    module_name = "tests.dynamic_cli_module_paths"
    module_file = tmp_path / "dynamic_cli_module_paths.py"
    module_file.write_text("value = 1\n", encoding="utf-8")
    module = ModuleType(module_name)
    module.__file__ = str(module_file)
    sys.modules[module_name] = module
    try:
        assert module_paths([module_name, "tests.missing_cli_module"]) == [module_file]

        snapshot = snapshot_module_mtimes([module_file, tmp_path / "missing.py"])
        assert snapshot == {module_file: module_file.stat().st_mtime}
        assert modules_changed(snapshot) is False
        assert modules_changed({module_file: snapshot[module_file] - 1}) is True

        module_file.unlink()
        assert modules_changed(snapshot) is True
    finally:
        sys.modules.pop(module_name, None)


def test_worker_start_and_queue_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeClient()
    monkeypatch.setattr("simpleq.cli_commands.shared.make_client", lambda **_: client)
    monkeypatch.setattr(
        "simpleq.cli_commands.shared.import_modules",
        lambda modules, reload=False: modules,
    )

    worker_start(queues=[], imports=[], concurrency=7, burst=False)
    assert client.worker_calls[0]["queues"] == [client.config.default_queue_name]

    worker_start(
        queues=["emails"], imports=["tests.fixtures.tasks"], concurrency=7, burst=True
    )
    assert client.worker_instance.calls == [False, True]
    assert client.worker_calls[1]["concurrency"] == 7

    worker_start(
        queues=["emails"],
        imports=["tests.fixtures.tasks"],
        burst=True,
    )
    assert client.worker_calls[2]["concurrency"] is None

    reload_calls: dict[str, object] = {}
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.run_reloading_worker",
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


def test_worker_start_reload_uses_default_queue_when_not_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    monkeypatch.setattr("simpleq.cli_commands.shared.make_client", lambda **_: client)
    monkeypatch.setattr(
        "simpleq.cli_commands.shared.import_modules",
        lambda modules, reload=False: modules,
    )

    reload_calls: dict[str, object] = {}
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.run_reloading_worker",
        lambda **kwargs: reload_calls.update(kwargs),
    )

    worker_start(
        queues=[],
        imports=["tests.fixtures.tasks"],
        concurrency=2,
        burst=False,
        reload=True,
    )

    assert reload_calls["queues"] == [client.config.default_queue_name]


def test_run_reloading_worker_rejects_missing_module_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    monkeypatch.setattr("simpleq.cli_commands.shared.make_client", lambda **_: client)
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.shared.load_registered_tasks",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.shared.module_paths", lambda imports: []
    )

    with pytest.raises(typer.BadParameter, match="Could not resolve import-module"):
        run_reloading_worker(
            queues=["emails"],
            imports=["tests.fixtures.tasks"],
            concurrency=1,
            burst=False,
            endpoint_url=None,
            region=None,
        )


def test_run_reloading_worker_restarts_on_code_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    watched_file = tmp_path / "watched.py"
    watched_file.write_text("value = 1\n", encoding="utf-8")

    class ReloadWorker(FakeWorker):
        def __init__(self) -> None:
            super().__init__()
            self.stop_calls = 0

        async def stop(self) -> None:
            self.stop_calls += 1

    class ReloadClient:
        def __init__(self) -> None:
            self.worker_instance = ReloadWorker()
            self.worker_calls: list[dict[str, object]] = []

        def worker(
            self, *, queues: list[str], concurrency: int | None = None
        ) -> ReloadWorker:
            self.worker_calls.append(
                {"queues": list(queues), "concurrency": concurrency}
            )
            return self.worker_instance

        def run_sync(self, awaitable: object) -> object:
            return (
                asyncio.run(awaitable) if asyncio.iscoroutine(awaitable) else awaitable
            )

    class FakeThread:
        def __init__(self, alive_states: list[bool]) -> None:
            self.alive_states = alive_states
            self.join_calls = 0
            self.started = False

        def start(self) -> None:
            self.started = True

        def is_alive(self) -> bool:
            if self.alive_states:
                return self.alive_states.pop(0)
            return False

        def join(self) -> None:
            self.join_calls += 1

    bootstrap_client = ReloadClient()
    first_client = ReloadClient()
    second_client = ReloadClient()
    created_clients = iter([bootstrap_client, first_client, second_client])
    load_calls: list[tuple[ReloadClient, bool]] = []
    invalidated = {"called": False}
    threads = [FakeThread([True]), FakeThread([False])]

    def fake_make_client(**_: object) -> ReloadClient:
        return next(created_clients)

    def fake_load_registered_tasks(
        client: ReloadClient, imports: list[str], *, reload: bool = False
    ) -> None:
        assert imports == ["tests.fixtures.tasks"]
        load_calls.append((client, reload))

    def fake_thread_factory(
        *, target: object, kwargs: dict[str, object], daemon: bool
    ) -> FakeThread:
        del target, kwargs, daemon
        return threads.pop(0)

    modules_changed_calls = iter([True])
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.shared.make_client", fake_make_client
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.shared.load_registered_tasks",
        fake_load_registered_tasks,
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.shared.module_paths",
        lambda imports: [watched_file],
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.shared.snapshot_module_mtimes",
        lambda paths: {watched_file: 1.0},
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.shared.modules_changed",
        lambda previous: next(modules_changed_calls, False),
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.threading.Thread", fake_thread_factory
    )
    monkeypatch.setattr("simpleq.cli_commands.worker.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.importlib.invalidate_caches",
        lambda: invalidated.__setitem__("called", True),
    )

    run_reloading_worker(
        queues=["emails"],
        imports=["tests.fixtures.tasks"],
        concurrency=2,
        burst=False,
        endpoint_url=None,
        region=None,
    )

    assert load_calls == [
        (bootstrap_client, False),
        (first_client, True),
        (second_client, True),
    ]
    assert first_client.worker_calls == [{"queues": ["emails"], "concurrency": 2}]
    assert second_client.worker_calls == [{"queues": ["emails"], "concurrency": 2}]
    assert first_client.worker_instance.stop_calls == 1
    assert invalidated["called"] is True
    assert "Detected code changes, restarting worker..." in capsys.readouterr().err


def test_run_reloading_worker_stops_before_reraising_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    watched_file = tmp_path / "watched.py"
    watched_file.write_text("value = 1\n", encoding="utf-8")

    class ReloadWorker(FakeWorker):
        def __init__(self) -> None:
            super().__init__()
            self.stop_calls = 0

        async def stop(self) -> None:
            self.stop_calls += 1

    class ReloadClient:
        def __init__(self) -> None:
            self.worker_instance = ReloadWorker()

        def worker(
            self, *, queues: list[str], concurrency: int | None = None
        ) -> ReloadWorker:
            del queues, concurrency
            return self.worker_instance

        def run_sync(self, awaitable: object) -> object:
            return (
                asyncio.run(awaitable) if asyncio.iscoroutine(awaitable) else awaitable
            )

    class FakeThread:
        def start(self) -> None:
            return None

        def is_alive(self) -> bool:
            return True

        def join(self) -> None:
            return None

    bootstrap_client = ReloadClient()
    runtime_client = ReloadClient()
    created_clients = iter([bootstrap_client, runtime_client])

    monkeypatch.setattr(
        "simpleq.cli_commands.worker.shared.make_client",
        lambda **_: next(created_clients),
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.shared.load_registered_tasks",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.shared.module_paths",
        lambda imports: [watched_file],
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.shared.snapshot_module_mtimes",
        lambda paths: {watched_file: 1.0},
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.threading.Thread",
        lambda **kwargs: FakeThread(),
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.worker.time.sleep",
        lambda seconds: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        run_reloading_worker(
            queues=["emails"],
            imports=["tests.fixtures.tasks"],
            concurrency=1,
            burst=False,
            endpoint_url=None,
            region=None,
        )

    assert runtime_client.worker_instance.stop_calls == 1


def test_dlq_cost_metrics_and_dashboard_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeClient()
    monkeypatch.setattr("simpleq.cli_commands.shared.make_client", lambda **_: client)

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
        "simpleq.cli_commands.monitoring.start_http_server",
        lambda port, addr, registry: metrics_calls.update(
            {"port": port, "addr": addr, "registry": registry}
        ),
    )
    monkeypatch.setattr(
        "simpleq.cli_commands.monitoring.time.sleep",
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
        "simpleq.cli_commands.monitoring.create_dashboard_server",
        lambda *args, **kwargs: fake_server,
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
    monkeypatch.setattr("simpleq.cli_commands.shared.make_client", lambda **_: client)

    queue_stats("emails")

    payload = json.loads(capsys.readouterr().out)
    assert payload["available_messages"] == 1
    assert payload["dlq_available_messages"] == 2


def test_doctor_and_task_list(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeClient()
    monkeypatch.setattr("simpleq.cli_commands.shared.make_client", lambda **_: client)

    doctor(check_sqs=False)
    task_list(imports=["tests.fixtures.tasks"])
    output_lines = capsys.readouterr().out.splitlines()
    doctor_payload = json.loads(output_lines[0])
    assert doctor_payload["config"]["endpoint_url"] == "http://localhost:4566"
    assert json.loads(output_lines[1]) == ["tests.fixtures.tasks:record_sync"]


def test_doctor_reports_sqs_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class HealthyClient(FakeClient):
        def list_queues_sync(self) -> list[str]:
            return ["emails", "orders"]

    class BrokenClient(FakeClient):
        def list_queues_sync(self) -> list[str]:
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "simpleq.cli_commands.shared.make_client",
        lambda **_: HealthyClient(),
    )
    doctor(check_sqs=True)
    healthy_payload = json.loads(capsys.readouterr().out)
    assert healthy_payload["sqs"] == {"ok": True, "queue_count": 2}

    monkeypatch.setattr(
        "simpleq.cli_commands.shared.make_client",
        lambda **_: BrokenClient(),
    )
    doctor(check_sqs=True)
    broken_payload = json.loads(capsys.readouterr().out)
    assert broken_payload["sqs"]["ok"] is False
    assert broken_payload["sqs"]["exception_type"] == "RuntimeError"


def test_job_enqueue_uses_registered_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    simpleq.task(queue="emails")(record_sync)
    monkeypatch.setattr("simpleq.cli_commands.shared.make_client", lambda **_: simpleq)
    monkeypatch.setattr(
        "simpleq.cli_commands.shared.import_modules",
        lambda modules, reload=False: modules,
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
        monkeypatch.setattr(
            "simpleq.cli_commands.shared.make_client",
            lambda **_: target,
        )

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


def test_job_enqueue_allows_queue_override(monkeypatch: pytest.MonkeyPatch) -> None:
    simpleq = SimpleQ(transport=InMemoryTransport())
    simpleq.task(queue="emails")(record_sync)
    monkeypatch.setattr("simpleq.cli_commands.shared.make_client", lambda **_: simpleq)
    monkeypatch.setattr(
        "simpleq.cli_commands.shared.import_modules",
        lambda modules, reload=False: modules,
    )

    job_enqueue(task_name_for(record_sync), queue="override", payload_json='["hello"]')

    received = simpleq.run_sync(
        simpleq.queue("override").receive(max_messages=1, wait_seconds=0)
    )
    assert len(received) == 1
    assert received[0].args == ("hello",)


def test_init_project_creates_scaffold(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    init_project(target=target)
    assert (target / "simpleq_app.py").exists()
    assert (target / ".env.example").exists()


def test_init_project_reports_skipped_and_force_overwrites(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "demo"
    target.mkdir()
    existing = target / "simpleq_app.py"
    existing.write_text("old scaffold\n", encoding="utf-8")

    init_project(target=target)
    initial_payload = json.loads(capsys.readouterr().out)
    assert "simpleq_app.py" in initial_payload["skipped"]
    assert existing.read_text(encoding="utf-8") == "old scaffold\n"

    init_project(target=target, force=True)
    forced_payload = json.loads(capsys.readouterr().out)
    assert "simpleq_app.py" in forced_payload["written"]
    assert "Starter SimpleQ application" in existing.read_text(encoding="utf-8")


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


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"args_json": "[1, 2]"}, ((1, 2), {})),
        ({"kwargs_json": '{"name": "value"}'}, ((), {"name": "value"})),
        ({"payload_json": '["hello"]'}, (("hello",), {})),
        ({"payload_json": '{"name": "value"}'}, ((), {"name": "value"})),
        ({"payload_json": '"hello"'}, (("hello",), {})),
        ({}, ((), {})),
    ],
)
def test_parse_invocation_payload_variants(
    kwargs: dict[str, str], expected: tuple[tuple[object, ...], dict[str, object]]
) -> None:
    assert parse_invocation_payload(**kwargs) == expected


@pytest.mark.parametrize(
    ("kwargs", "expected_message"),
    [
        (
            {"args_json": '{"name": "value"}'},
            "--args-json must decode to a JSON array.",
        ),
        (
            {"kwargs_json": '["value"]'},
            "--kwargs-json must decode to a JSON object.",
        ),
        (
            {"args_json": "[]", "payload_json": "{}"},
            "Use only one of --args-json, --kwargs-json, or --payload-json.",
        ),
    ],
)
def test_parse_invocation_payload_rejects_invalid_shapes(
    kwargs: dict[str, str], expected_message: str
) -> None:
    with pytest.raises(typer.BadParameter, match=expected_message):
        parse_invocation_payload(**kwargs)
