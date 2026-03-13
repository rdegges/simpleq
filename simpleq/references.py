"""Queue name parsing helpers for SQS references."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from simpleq.exceptions import QueueValidationError
from simpleq.queue import normalize_queue_name


def queue_name_from_reference(reference: str) -> str | None:
    """Extract a queue name from either a URL, ARN, or queue-name-like reference."""
    normalized = reference.strip()
    if not normalized:
        return None
    if normalized.startswith("arn:"):
        return _queue_name_from_arn(normalized)
    if "://" not in normalized:
        candidate = normalized.rstrip("/").rsplit("/", 1)[-1]
        return _validated_queue_name(candidate)

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        return None
    path = parsed.path.rstrip("/")
    if not path:
        return None
    queue_name = unquote(path.rsplit("/", 1)[-1])
    return _validated_queue_name(queue_name)


def _validated_queue_name(candidate: str) -> str | None:
    """Return a normalized queue name or ``None`` when the candidate is invalid."""
    if not candidate:
        return None
    try:
        return normalize_queue_name(candidate, fifo=candidate.endswith(".fifo"))
    except QueueValidationError:
        return None


def _queue_name_from_arn(arn: str) -> str | None:
    """Extract an SQS queue name from a queue ARN."""
    parts = arn.split(":", 5)
    if len(parts) != 6:
        return None
    _arn, _partition, service, _region, _account_id, resource = parts
    if service != "sqs":
        return None
    return _validated_queue_name(resource)
