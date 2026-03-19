"""SimpleQ — the main application entry point."""

from __future__ import annotations

from typing import Any, Callable

from simpleq.config import Config
from simpleq.cost import CostTracker
from simpleq.queue import Queue
from simpleq.task import Task


class SimpleQ:
    """The main SimpleQ application.

    Creates a task registry, manages queues, and provides the @task decorator.

    Usage:
        sq = SimpleQ()

        @sq.task
        def send_email(to, subject, body):
            ...

        send_email.delay("user@example.com", "Hello", "Welcome!")
    """

    def __init__(
        self,
        region: str = "us-east-1",
        dead_letter_queue: bool = False,
        visibility_timeout: int = 30,
        auto_create: bool = True,
        endpoint_url: str | None = None,
    ) -> None:
        self.config = Config(
            region=region,
            dead_letter_queue=dead_letter_queue,
            visibility_timeout=visibility_timeout,
            auto_create=auto_create,
            endpoint_url=endpoint_url,
        )
        self.cost_tracker = CostTracker()
        self._queues: dict[str, Queue] = {}
        self._tasks: dict[str, Task] = {}

    def queue(self, name: str = "default") -> Queue:
        """Get or create a Queue object by name.

        Queue objects are cached — calling queue("emails") twice returns the
        same object.
        """
        if name not in self._queues:
            self._queues[name] = Queue(
                name=name,
                config=self.config,
                cost_tracker=self.cost_tracker,
            )
        return self._queues[name]

    @property
    def tasks(self) -> dict[str, Task]:
        """All registered tasks."""
        return dict(self._tasks)

    @property
    def queues(self) -> dict[str, Queue]:
        """All known queues."""
        return dict(self._queues)

    def task(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        queue: str = "default",
        retries: int = 0,
        backoff: str = "exponential",
        async_: bool = False,
        fifo: bool = False,
        message_group_id: Callable[..., str] | str | None = None,
        lambda_: bool = False,
    ) -> Any:
        """Decorator to register a function as a background task.

        Can be used with or without arguments:

            @sq.task
            def simple_task():
                ...

            @sq.task(queue="emails", retries=3)
            def email_task():
                ...
        """

        def decorator(func: Callable[..., Any]) -> Task:
            task_obj = Task(
                fn=func,
                app=self,
                queue=queue,
                retries=retries,
                backoff=backoff,
                async_=async_,
                fifo=fifo,
                message_group_id=message_group_id,
                lambda_=lambda_,
            )
            self._tasks[task_obj.name] = task_obj
            return task_obj

        # Support both @sq.task and @sq.task(queue="emails")
        if fn is not None:
            return decorator(fn)
        return decorator
