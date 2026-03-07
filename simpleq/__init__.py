"""Public package API for SimpleQ."""

from __future__ import annotations

from simpleq.client import SimpleQ
from simpleq.job import Job
from simpleq.queue import Queue
from simpleq.task import TaskHandle
from simpleq.testing import InMemoryTransport
from simpleq.worker import Worker

__all__ = [
    "InMemoryTransport",
    "Job",
    "Queue",
    "SimpleQ",
    "TaskHandle",
    "Worker",
    "__version__",
]

__version__ = "2.0.0"
