"""Task decorator — turns functions into background jobs."""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, Callable

from simpleq.job import Job

if TYPE_CHECKING:
    from simpleq.app import SimpleQ


class Task:
    """A decorated function that can be enqueued as a background job.

    Tasks are created by the @sq.task decorator and have two main methods:
    - .delay() — serialize arguments and send to SQS
    - .apply() — run the function locally without touching SQS
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        app: SimpleQ,
        queue: str = "default",
        retries: int = 0,
        backoff: str = "exponential",
        async_: bool = False,
        fifo: bool = False,
        message_group_id: Callable[..., str] | str | None = None,
        lambda_: bool = False,
    ) -> None:
        self.fn = fn
        self.app = app
        self.name = f"{fn.__module__}.{fn.__qualname__}"
        self.retries = retries
        self.backoff = backoff
        self.async_ = async_
        self.fifo = fifo
        self.message_group_id = message_group_id
        self.lambda_ = lambda_

        # Auto-append .fifo suffix for FIFO queues
        if fifo and not queue.endswith(".fifo"):
            self.queue_name = f"{queue}.fifo"
        else:
            self.queue_name = queue

        # Make Task callable and preserve original function metadata
        functools.update_wrapper(self, fn)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the underlying function directly."""
        return self.fn(*args, **kwargs)

    def delay(
        self, *args: Any, _delay_seconds: int = 0, **kwargs: Any
    ) -> None:
        """Serialize arguments and send to SQS for background processing."""
        job = Job(
            task_name=self.name,
            args=args,
            kwargs=kwargs,
        )

        # Resolve message_group_id for FIFO queues
        group_id = None
        if self.fifo and self.message_group_id is not None:
            if callable(self.message_group_id):
                group_id = self.message_group_id(*args, **kwargs)
            else:
                group_id = self.message_group_id

        queue = self.app.queue(self.queue_name)
        queue.send_job(
            job,
            delay_seconds=_delay_seconds,
            message_group_id=group_id,
        )

    def apply(self, *args: Any, **kwargs: Any) -> Any:
        """Run the function locally without touching SQS."""
        return self.fn(*args, **kwargs)
