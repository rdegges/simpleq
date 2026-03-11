"""Task registration and dispatch helpers."""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any, Generic, ParamSpec, TypeVar, cast

from pydantic import BaseModel

from simpleq._sync import run_sync
from simpleq.exceptions import InvalidTaskError, TaskNotRegisteredError
from simpleq.job import Job

P = ParamSpec("P")
R = TypeVar("R")
SchemaT = TypeVar("SchemaT", bound=BaseModel)
Resolver = str | Callable[..., str]


@dataclass(slots=True)
class TaskDefinition:
    """Immutable task registration metadata."""

    name: str
    func: Callable[..., Any]
    queue_ref: Any | None = None
    serializer: str = "json"
    schema: type[BaseModel] | None = None
    message_group_id: Resolver | None = None
    deduplication_id: Resolver | None = None
    retry_exceptions: tuple[type[BaseException], ...] | None = None
    max_retries: int | None = None

    @property
    def is_async(self) -> bool:
        """Return whether the underlying task is async."""
        return inspect.iscoroutinefunction(self.func)


def task_name_for(func: Callable[..., Any]) -> str:
    """Return a stable import path for a task."""
    qualname = func.__qualname__
    if "<locals>" in qualname:
        raise InvalidTaskError("Tasks must be defined at module scope.")
    return f"{func.__module__}:{qualname}"


def import_task_callable(task_name: str) -> Callable[..., Any]:
    """Import a task callable by its fully-qualified task name."""
    return import_task_definition(task_name).func


def import_task_definition(task_name: str) -> TaskDefinition:
    """Import a task definition by its fully-qualified task name."""
    module_name, sep, attr_path = task_name.partition(":")
    if not sep:
        raise TaskNotRegisteredError(f"Invalid task name: {task_name}")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise TaskNotRegisteredError(
            f"Could not import module '{module_name}' for task '{task_name}': {exc}"
        ) from exc
    target: Any = module
    try:
        for part in attr_path.split("."):
            target = getattr(target, part)
    except AttributeError as exc:
        raise TaskNotRegisteredError(
            f"Could not resolve task attribute '{attr_path}' in module "
            f"'{module_name}'."
        ) from exc
    if isinstance(target, TaskHandle):
        return replace(target.definition, name=task_name)
    if callable(target):
        return TaskDefinition(name=task_name, func=cast("Callable[..., Any]", target))
    raise TaskNotRegisteredError(f"Task '{task_name}' did not resolve to a callable.")


class TaskRegistry:
    """In-memory task registry for a SimpleQ instance."""

    def __init__(self) -> None:
        self._definitions: dict[str, TaskDefinition] = {}

    def register(self, definition: TaskDefinition) -> None:
        """Register a task definition."""
        self._definitions[definition.name] = definition

    def get(self, task_name: str) -> TaskDefinition:
        """Return a task definition or import the callable if needed."""
        if definition := self._definitions.get(task_name):
            return definition
        definition = import_task_definition(task_name)
        self._definitions[task_name] = definition
        return definition

    def names(self) -> list[str]:
        """Return registered task names in sorted order."""
        return sorted(self._definitions)


class TaskHandle(Generic[P, R]):
    """User-facing task wrapper with enqueue helpers."""

    def __init__(self, simpleq: Any, definition: TaskDefinition) -> None:
        self._simpleq = simpleq
        self.definition = definition
        self.__name__ = definition.func.__name__
        self.__doc__ = definition.func.__doc__
        self.__module__ = definition.func.__module__

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R | Awaitable[R]:
        """Execute the local callable directly."""
        return cast("R | Awaitable[R]", self.definition.func(*args, **kwargs))

    async def delay(
        self,
        *args: Any,
        delay_seconds: int = 0,
        message_group_id: str | None = None,
        deduplication_id: str | None = None,
        attributes: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Job:
        """Validate arguments and enqueue a task invocation."""
        queue = self._simpleq.resolve_queue(self.definition.queue_ref)
        normalized_args, normalized_kwargs = self._normalize_arguments(args, kwargs)
        resolved_group_id = message_group_id or resolve_value(
            self.definition.message_group_id,
            args,
            kwargs,
        )
        resolved_dedup_id = deduplication_id or resolve_value(
            self.definition.deduplication_id,
            args,
            kwargs,
        )
        job = Job(
            task_name=self.definition.name,
            args=normalized_args,
            kwargs=normalized_kwargs,
            queue_name=queue.name,
            serializer=self.definition.serializer,
        )
        await queue.enqueue(
            job,
            delay_seconds=delay_seconds,
            message_group_id=resolved_group_id,
            deduplication_id=resolved_dedup_id,
            attributes=attributes,
        )
        return job

    def delay_sync(
        self,
        *args: Any,
        delay_seconds: int = 0,
        message_group_id: str | None = None,
        deduplication_id: str | None = None,
        attributes: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Job:
        """Synchronous wrapper around :meth:`delay`."""
        return run_sync(
            self.delay(
                *args,
                delay_seconds=delay_seconds,
                message_group_id=message_group_id,
                deduplication_id=deduplication_id,
                attributes=attributes,
                **kwargs,
            )
        )

    def _normalize_arguments(
        self, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[Any, dict[str, Any]]:
        schema = self.definition.schema
        if schema is None:
            return tuple(args), dict(kwargs)

        model = normalize_schema_input(schema, args, kwargs)
        return (model.model_dump(mode="json"),), {}


def normalize_schema_input(
    schema: type[SchemaT],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> SchemaT:
    """Normalize task arguments for a Pydantic schema task."""
    if args and kwargs:
        raise InvalidTaskError("Schema tasks must use either args or kwargs, not both.")
    if len(args) > 1:
        raise InvalidTaskError("Schema tasks accept a single positional payload.")
    if args:
        return schema.model_validate(args[0])
    return schema.model_validate(kwargs)


def resolve_value(
    value: Resolver | None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str | None:
    """Resolve a string or callable task option."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value(*args, **kwargs)
