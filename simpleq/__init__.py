"""SimpleQ — The Python task queue for AWS."""

from simpleq.app import SimpleQ
from simpleq.exceptions import (
    ConfigurationError,
    MessageTooLargeError,
    QueueError,
    QueueNotFoundError,
    RetryExhaustedError,
    SerializationError,
    SimpleQError,
    TaskError,
    TaskNotFoundError,
)
from simpleq.job import Job
from simpleq.queue import Queue
from simpleq.task import Task
from simpleq.worker import Worker

__version__ = "2.0.0"

__all__ = [
    "SimpleQ",
    "Queue",
    "Task",
    "Worker",
    "Job",
    "SimpleQError",
    "ConfigurationError",
    "QueueError",
    "QueueNotFoundError",
    "SerializationError",
    "MessageTooLargeError",
    "TaskError",
    "TaskNotFoundError",
    "RetryExhaustedError",
]
