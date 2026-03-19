"""SimpleQ exception hierarchy."""

from __future__ import annotations


class SimpleQError(Exception):
    """Base exception for all SimpleQ errors."""


class ConfigurationError(SimpleQError):
    """Raised when configuration is invalid or AWS credentials are missing."""


class QueueError(SimpleQError):
    """Base exception for queue-related errors."""


class QueueNotFoundError(QueueError):
    """Raised when a queue doesn't exist and auto_create is disabled."""


class SerializationError(SimpleQError):
    """Raised when job serialization or deserialization fails."""


class MessageTooLargeError(SerializationError):
    """Raised when a serialized payload exceeds the SQS 256KB limit."""


class TaskError(SimpleQError):
    """Base exception for task-related errors."""


class TaskNotFoundError(TaskError):
    """Raised when a worker receives a job for an unregistered task."""


class RetryExhaustedError(TaskError):
    """Raised when all retries for a task are exhausted."""
