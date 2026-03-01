"""This module holds our job abstractions."""

from __future__ import annotations

from datetime import datetime
from pickle import dumps, loads
from typing import Any, Callable


class Job:
    """An abstraction for a single unit of work (a job!)."""

    def __init__(
        self,
        callable: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Create a new Job.

        Args:
            callable: A callable to run.
            *args: Positional arguments for the callable.
            **kwargs: Keyword arguments for the callable.
        """
        self.start_time: datetime | None = None
        self.stop_time: datetime | None = None
        self.run_time: float | None = None
        self.exception: Exception | None = None
        self.result: Any = None
        self.callable = callable
        self.args = args
        self.kwargs = kwargs
        self._message_body: bytes | None = None

    @property
    def message_body(self) -> bytes:
        """Get the serialized message body.

        Returns:
            Pickled message body as bytes.
        """
        if self._message_body is None:
            self._message_body = dumps({
                'callable': self.callable,
                'args': self.args,
                'kwargs': self.kwargs,
            })
        return self._message_body

    def __repr__(self) -> str:
        """Print a human-friendly object representation."""
        return f'<Job({{"callable": "{self.callable.__name__}"}}))>'

    @classmethod
    def from_message(cls, message_body: str) -> Job:
        """Create a new Job from a message body.

        Args:
            message_body: The message body string from SQS.

        Returns:
            A new Job instance.
        """
        data = loads(message_body.encode() if isinstance(message_body, str) else message_body)
        job = cls(data['callable'], *data['args'], **data['kwargs'])
        return job

    def log(self, message: str) -> None:
        """Write the given message to standard out (STDOUT).

        Args:
            message: The message to log.
        """
        print(f'simpleq: {message}')

    def run(self) -> None:
        """Run this job."""
        self.start_time = datetime.utcnow()
        self.log(
            f'Starting job {self.callable.__name__} at {self.start_time.isoformat()}.'
        )

        try:
            self.result = self.callable(*self.args, **self.kwargs)
        except Exception as e:
            self.exception = e

        if not self.exception:
            self.stop_time = datetime.utcnow()
            self.run_time = (self.stop_time - self.start_time).total_seconds()
            self.log(
                f'Finished job {self.callable.__name__} at '
                f'{self.stop_time.isoformat()} in {self.run_time} seconds.'
            )
        else:
            self.log(
                f'Job {self.callable.__name__} failed to run: {self.exception}'
            )
