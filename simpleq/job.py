"""Job model and SQS message conversion."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from simpleq.serializers import JSONValue, get_serializer

MESSAGE_GROUP_METADATA_KEY = "_simpleq_message_group_id"
DEDUPLICATION_METADATA_KEY = "_simpleq_deduplication_id"
LEGACY_MESSAGE_GROUP_METADATA_KEY = "message_group_id"
LEGACY_DEDUPLICATION_METADATA_KEY = "deduplication_id"


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Job:
    """Serializable representation of a queued task execution."""

    task_name: str
    args: Any
    kwargs: Any
    queue_name: str
    serializer: str = "json"
    job_id: str = field(default_factory=lambda: uuid4().hex)
    attempt: int = 0
    enqueued_at: datetime = field(default_factory=utcnow)
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    receipt_handle: str | None = None
    message_id: str | None = None
    receive_count: int = 1
    message_attributes: dict[str, str] = field(default_factory=dict)

    def to_payload(self) -> dict[str, JSONValue]:
        """Return a versioned JSON payload for SQS message bodies."""
        serializer = get_serializer(self.serializer)
        return {
            "version": "2.0",
            "job_id": self.job_id,
            "task_name": self.task_name,
            "queue_name": self.queue_name,
            "serializer": self.serializer,
            "args": serializer.dump(self.args),
            "kwargs": serializer.dump(self.kwargs),
            "attempt": self.attempt,
            "enqueued_at": self.enqueued_at.isoformat(),
            "metadata": self.metadata,
        }

    def to_message_body(self) -> str:
        """Encode this job as a JSON string."""
        return json.dumps(self.to_payload())

    @classmethod
    def from_message_body(
        cls,
        message_body: str,
        *,
        receipt_handle: str | None = None,
        message_id: str | None = None,
        receive_count: int = 1,
        message_attributes: dict[str, str] | None = None,
    ) -> Job:
        """Decode a job from an SQS message body."""
        payload = json.loads(message_body)
        serializer_name = str(payload["serializer"])
        serializer = get_serializer(serializer_name)
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise TypeError("Job metadata must be a mapping.")
        return cls(
            job_id=str(payload["job_id"]),
            task_name=str(payload["task_name"]),
            queue_name=str(payload["queue_name"]),
            serializer=serializer_name,
            args=tuple(serializer.load(payload["args"])),
            kwargs=dict(serializer.load(payload["kwargs"])),
            attempt=int(payload.get("attempt", 0)),
            enqueued_at=datetime.fromisoformat(str(payload["enqueued_at"])),
            metadata=metadata,
            receipt_handle=receipt_handle,
            message_id=message_id,
            receive_count=receive_count,
            message_attributes=message_attributes or {},
        )

    @classmethod
    def from_sqs_message(cls, queue_name: str, message: dict[str, Any]) -> Job:
        """Build a job instance from an SQS message dictionary."""
        system_attributes = message.get("Attributes", {})
        attribute_payload = message.get("MessageAttributes", {})
        string_attributes: dict[str, str] = {}
        if isinstance(attribute_payload, dict):
            for key, value in attribute_payload.items():
                if not isinstance(key, str) or not isinstance(value, dict):
                    continue
                string_value = value.get("StringValue")
                if string_value is None:
                    continue
                string_attributes[key] = str(string_value)
        job = cls.from_message_body(
            str(message["Body"]),
            receipt_handle=message.get("ReceiptHandle"),
            message_id=message.get("MessageId"),
            receive_count=int(system_attributes.get("ApproximateReceiveCount", "1")),
            message_attributes=string_attributes,
        )
        if job.queue_name != queue_name:
            job.queue_name = queue_name
        _attach_system_routing_metadata(job, system_attributes)
        return job

    def with_attempt(self, attempt: int, *, error: str | None = None) -> Job:
        """Return a copy with updated retry metadata."""
        metadata = dict(self.metadata)
        if error is not None:
            metadata["last_error"] = error
        return replace(self, attempt=attempt, metadata=metadata)


def _attach_system_routing_metadata(job: Job, system_attributes: Any) -> None:
    """Persist FIFO routing metadata from SQS system attributes when available."""
    if not isinstance(system_attributes, dict):
        return

    metadata = dict(job.metadata)
    changed = _set_metadata_value(
        metadata,
        MESSAGE_GROUP_METADATA_KEY,
        system_attributes.get("MessageGroupId"),
    )
    changed = (
        _set_metadata_value(
            metadata,
            LEGACY_MESSAGE_GROUP_METADATA_KEY,
            system_attributes.get("MessageGroupId"),
        )
        or changed
    )
    changed = (
        _set_metadata_value(
            metadata,
            DEDUPLICATION_METADATA_KEY,
            system_attributes.get("MessageDeduplicationId"),
        )
        or changed
    )
    changed = (
        _set_metadata_value(
            metadata,
            LEGACY_DEDUPLICATION_METADATA_KEY,
            system_attributes.get("MessageDeduplicationId"),
        )
        or changed
    )
    if changed:
        job.metadata = metadata


def _set_metadata_value(
    metadata: dict[str, JSONValue], key: str, value: Any
) -> bool:
    """Store the latest stringified routing metadata from the SQS envelope."""
    if value is None:
        return False
    string_value = str(value)
    if metadata.get(key) == string_value:
        return False
    metadata[key] = string_value
    return True
