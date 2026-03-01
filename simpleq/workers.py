"""Our worker implementation."""

from __future__ import annotations

from time import sleep
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from simpleq.queues import Queue


class Worker:
    """A simple queue worker.

    This worker listens to one or more queues for jobs, then executes each job
    to complete the work.
    """

    def __init__(self, queues: list[Queue], concurrency: int = 10) -> None:
        """Initialize a new worker.

        Args:
            queues: A list of queues to monitor.
            concurrency: The amount of jobs to process concurrently.
                Depending on what type of concurrency is in use (either gevent, or
                multiprocessing), this may correlate to either green threads or
                CPU processes, respectively.
        """
        self.queues = queues
        self.concurrency = concurrency

    def __repr__(self) -> str:
        """Print a human-friendly object representation."""
        return f'<Worker({{"queues": {self.queues!r}}}))>'

    def work(self, burst: bool = False, wait_seconds: int = 5) -> None:
        """Monitor all queues and execute jobs.

        Once started, this will run forever (unless the burst option is True).

        Args:
            burst: Should we quickly burst and finish all existing jobs then quit?
            wait_seconds: Seconds to wait between polling iterations.
        """
        while True:
            for queue in self.queues:
                for job, message in queue.jobs:
                    job.run()
                    queue.remove_job(message)

            if burst:
                break
            sleep(wait_seconds)
