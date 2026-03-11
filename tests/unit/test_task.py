"""Unit tests for task registration behavior."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from simpleq import SimpleQ
from simpleq.exceptions import (
    InvalidTaskError,
    QueueValidationError,
    TaskNotRegisteredError,
)
from simpleq.task import (
    TaskDefinition,
    TaskHandle,
    TaskRegistry,
    import_task_callable,
    normalize_schema_input,
    resolve_value,
    task_name_for,
)
from tests.fixtures.tasks import EmailPayload, record_async, record_sync, schema_task


class DummyQueue:
    """Simple fake queue used to inspect enqueued jobs."""

    def __init__(self) -> None:
        self.name = "default"
        self.jobs: list[object] = []

    async def enqueue(self, job: object, **_: object) -> str:
        self.jobs.append(job)
        return "mid"


class DummySimpleQ:
    """Small fake SimpleQ facade for TaskHandle tests."""

    def __init__(self) -> None:
        self.queue = DummyQueue()

    def resolve_queue(self, queue_ref: object) -> DummyQueue:
        return self.queue


def test_task_name_for_rejects_nested_functions() -> None:
    def nested() -> None:
        return None

    with pytest.raises(InvalidTaskError):
        task_name_for(nested)


@pytest.mark.asyncio
async def test_task_handle_normalizes_schema_payload() -> None:
    definition = TaskDefinition(
        name="tests.fixtures.tasks:schema_task",
        func=record_async,
        schema=EmailPayload,
    )
    handle = TaskHandle(DummySimpleQ(), definition)
    job = await handle.delay(to="to@example.com", subject="Hello", body="Body")
    assert job.args == ({"to": "to@example.com", "subject": "Hello", "body": "Body"},)


def test_normalize_schema_input_rejects_multiple_args() -> None:
    with pytest.raises(InvalidTaskError):
        normalize_schema_input(EmailPayload, ("a", "b"), {})


def test_resolve_value_supports_strings_and_callables() -> None:
    assert resolve_value("fixed", ("a",), {}) == "fixed"
    assert resolve_value(lambda value: f"group-{value}", ("a",), {}) == "group-a"


def test_simpleq_task_decorator_registers_handle() -> None:
    simpleq = SimpleQ()
    handle = simpleq.task()(record_async)
    assert isinstance(handle, TaskHandle)
    assert simpleq.registry.get(task_name_for(record_async)).func is record_async


def test_import_task_callable_and_registry_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("tests.dynamic_module")
    simpleq = SimpleQ()
    handle = simpleq.task()(record_async)
    module.handle = handle
    module.not_callable = []
    sys.modules[module.__name__] = module
    try:
        assert import_task_callable("tests.dynamic_module:handle") is record_async
        with pytest.raises(TaskNotRegisteredError):
            import_task_callable("tests.dynamic_module:not_callable")

        registry = TaskRegistry()
        loaded = registry.get("tests.dynamic_module:handle")
        assert loaded.func is record_async
    finally:
        sys.modules.pop(module.__name__, None)


def test_task_registry_preserves_task_handle_metadata() -> None:
    module = ModuleType("tests.dynamic_schema_module")
    simpleq = SimpleQ()
    module.handle = simpleq.task(
        schema=EmailPayload,
        max_retries=5,
        retry_exceptions=[RuntimeError],
    )(schema_task)
    sys.modules[module.__name__] = module
    try:
        loaded = TaskRegistry().get("tests.dynamic_schema_module:handle")
        assert loaded.name == "tests.dynamic_schema_module:handle"
        assert loaded.func is schema_task
        assert loaded.schema is EmailPayload
        assert loaded.max_retries == 5
        assert loaded.retry_exceptions == (RuntimeError,)
    finally:
        sys.modules.pop(module.__name__, None)


def test_import_task_callable_rejects_invalid_name() -> None:
    with pytest.raises(TaskNotRegisteredError):
        import_task_callable("invalid-name")


def test_import_task_callable_rejects_missing_module() -> None:
    with pytest.raises(TaskNotRegisteredError, match="Could not import module"):
        import_task_callable("tests.module_does_not_exist:record_sync")


def test_import_task_callable_rejects_missing_attribute() -> None:
    with pytest.raises(TaskNotRegisteredError, match="Could not resolve task attribute"):
        import_task_callable("tests.fixtures.tasks:not_a_real_task")


def test_import_task_callable_plain_function() -> None:
    assert import_task_callable("tests.fixtures.tasks:record_sync") is record_sync


def test_task_handle_call_and_delay_sync() -> None:
    definition = TaskDefinition(
        name="tests.fixtures.tasks:record_async", func=lambda value: value
    )
    handle = TaskHandle(DummySimpleQ(), definition)
    assert handle("hello") == "hello"
    job = handle.delay_sync("hello")
    assert job.args == ("hello",)


@pytest.mark.asyncio
async def test_task_delay_surfaces_invalid_fifo_resolver_types() -> None:
    simpleq = SimpleQ()
    queue = simpleq.queue("orders.fifo", fifo=True)
    handle = TaskHandle(
        simpleq,
        TaskDefinition(
            name="tests.fixtures.tasks:record_async",
            func=record_async,
            queue_ref=queue,
            message_group_id=lambda value: value,
            deduplication_id=lambda value: f"dedup-{value}",
        ),
    )

    with pytest.raises(QueueValidationError, match="message_group_id must be a string"):
        await handle.delay(123)


def test_normalize_schema_input_additional_branches() -> None:
    model = normalize_schema_input(
        EmailPayload,
        ({"to": "to@example.com", "subject": "Hello", "body": "Body"},),
        {},
    )
    assert model.to == "to@example.com"
    with pytest.raises(InvalidTaskError):
        normalize_schema_input(EmailPayload, ("a",), {"subject": "b"})
