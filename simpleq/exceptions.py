"""SimpleQ exception hierarchy."""

from __future__ import annotations


class SimpleQError(Exception):
    """Base exception for all SimpleQ errors."""


class ConfigurationError(SimpleQError):
    """Raised when SimpleQ is configured incorrectly."""


class QueueError(SimpleQError):
    """Base exception for queue-related errors."""


class QueueValidationError(QueueError):
    """Raised when queue configuration is invalid."""


class QueueNotFoundError(QueueError):
    """Raised when an SQS queue does not exist."""


class QueueBatchError(QueueError):
    """Raised when a batch queue operation partially fails."""


class TaskError(SimpleQError):
    """Base exception for task-related errors."""


class InvalidTaskError(TaskError):
    """Raised when a task definition is invalid."""


class TaskNotRegisteredError(TaskError):
    """Raised when a worker cannot resolve a task."""


class SerializationError(SimpleQError):
    """Raised when task arguments cannot be serialized."""


class RetryExhaustedError(SimpleQError):
    """Raised when retries are exhausted outside a DLQ flow."""
