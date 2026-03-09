"""SQS queue abstraction for SimpleQ."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from simpleq._sync import run_sync
from simpleq.exceptions import QueueValidationError
from simpleq.job import (
    DEDUPLICATION_METADATA_KEY,
    LEGACY_DEDUPLICATION_METADATA_KEY,
    LEGACY_MESSAGE_GROUP_METADATA_KEY,
    MESSAGE_GROUP_METADATA_KEY,
    Job,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

_QUEUE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_MESSAGE_ATTRIBUTE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_QUEUE_NAME_LENGTH = 80
_MAX_RECEIVE_MESSAGES = 10
_MAX_WAIT_SECONDS = 20
_MAX_VISIBILITY_TIMEOUT = 43_200
_MAX_MESSAGE_ATTRIBUTES = 10
_MAX_MESSAGE_ATTRIBUTE_NAME_LENGTH = 256
_MAX_MESSAGE_ATTRIBUTE_VALUE_BYTES = 262_144
_MAX_FIFO_ROUTING_ID_LENGTH = 128
_MAX_DLQ_MAX_RECEIVE_COUNT = 1000


@dataclass(frozen=True, slots=True)
class QueueStats:
    """High-level queue statistics."""

    name: str
    fifo: bool
    dlq_name: str | None
    available_messages: int
    in_flight_messages: int
    delayed_messages: int


@dataclass(frozen=True, slots=True)
class BatchEntry:
    """Batch enqueue entry."""

    job: Job
    delay_seconds: int = 0
    message_group_id: str | None = None
    deduplication_id: str | None = None
    attributes: dict[str, str] | None = None


def encode_message_attributes(
    attributes: dict[str, str] | None,
) -> dict[str, dict[str, str]]:
    """Encode simple string attributes into SQS message attribute shape."""
    if not attributes:
        return {}
    if len(attributes) > _MAX_MESSAGE_ATTRIBUTES:
        raise QueueValidationError(
            f"message attributes support at most {_MAX_MESSAGE_ATTRIBUTES} entries."
        )
    for key, value in attributes.items():
        if not key:
            raise QueueValidationError("message attribute names must be non-empty.")
        if len(key) > _MAX_MESSAGE_ATTRIBUTE_NAME_LENGTH:
            raise QueueValidationError(
                "message attribute names must be between 1 and 256 characters."
            )
        if _MESSAGE_ATTRIBUTE_NAME_PATTERN.fullmatch(key) is None:
            raise QueueValidationError(
                "message attribute names may only contain letters, numbers, hyphens, underscores, or periods."
            )
        if not isinstance(value, str):
            raise QueueValidationError("message attribute values must be strings.")
        if len(value.encode("utf-8")) > _MAX_MESSAGE_ATTRIBUTE_VALUE_BYTES:
            raise QueueValidationError(
                "message attribute values must be at most 262144 bytes."
            )
    return {
        key: {"DataType": "String", "StringValue": value}
        for key, value in attributes.items()
    }


class Queue:
    """High-level queue abstraction built on Amazon SQS."""

    def __init__(
        self,
        simpleq: Any,
        name: str,
        *,
        fifo: bool = False,
        dlq: bool = False,
        max_retries: int | None = None,
        content_based_deduplication: bool = False,
        visibility_timeout: int | None = None,
        wait_seconds: int | None = None,
        tags: dict[str, str] | None = None,
    ) -> None:
        self.simpleq = simpleq
        self.config = simpleq.config
        self.name = normalize_queue_name(name, fifo=fifo)
        self.fifo = fifo
        self.dlq = dlq
        self.max_retries = (
            self.config.max_retries if max_retries is None else max_retries
        )
        self.content_based_deduplication = content_based_deduplication
        self.visibility_timeout = (
            self.config.visibility_timeout
            if visibility_timeout is None
            else visibility_timeout
        )
        self.wait_seconds = (
            self.config.wait_seconds if wait_seconds is None else wait_seconds
        )
        self._tags_configured = tags is not None
        self.tags = tags or {}
        if self.dlq and (
            self.max_retries < 1 or self.max_retries > _MAX_DLQ_MAX_RECEIVE_COUNT
        ):
            raise QueueValidationError(
                f"DLQ max_retries must be between 1 and {_MAX_DLQ_MAX_RECEIVE_COUNT}."
            )
        self._queue_url: str | None = None
        self._dlq_url: str | None = None
        self._validate_receive_options(
            max_messages=self.batch_size,
            wait_seconds=self.wait_seconds,
            visibility_timeout=self.visibility_timeout,
        )

    def __repr__(self) -> str:
        """Return a readable queue representation."""
        return f"Queue(name={self.name!r}, fifo={self.fifo}, dlq={self.dlq})"

    @property
    def batch_size(self) -> int:
        """Return the configured receive batch size."""
        return int(self.config.batch_size)

    @property
    def dlq_name(self) -> str | None:
        """Return the DLQ name if DLQ support is enabled."""
        if not self.dlq:
            return None
        if self.fifo:
            return self.name.removesuffix(".fifo") + "-dlq.fifo"
        return f"{self.name}-dlq"

    async def ensure_exists(self) -> str:
        """Ensure the queue, and its DLQ if configured, exist."""
        if self._queue_url is not None:
            return self._queue_url

        if self.dlq and self.dlq_name is not None:
            dlq_attributes = self._create_queue_attributes(
                fifo=self.fifo,
                content_based_deduplication=self.content_based_deduplication,
            )
            self._dlq_url = await self.simpleq.transport.ensure_queue(
                self.dlq_name,
                attributes=dlq_attributes,
                tags=self.tags if self._tags_configured else None,
            )
            dlq_arn = await self.simpleq.transport.queue_arn(
                self.dlq_name, self._dlq_url
            )
        else:
            dlq_arn = None

        attributes = self._create_queue_attributes(
            fifo=self.fifo,
            content_based_deduplication=self.content_based_deduplication,
            dlq_arn=dlq_arn,
        )
        self._queue_url = await self.simpleq.transport.ensure_queue(
            self.name,
            attributes=attributes,
            tags=self.tags if self._tags_configured else None,
        )
        return self._queue_url

    def ensure_exists_sync(self) -> str:
        """Synchronous wrapper for :meth:`ensure_exists`."""
        return run_sync(self.ensure_exists())

    async def delete(self) -> None:
        """Delete the queue and its DLQ when present."""
        queue_url = await self.ensure_exists()
        await self.simpleq.transport.delete_queue(self.name, queue_url)
        if self.dlq_name and self._dlq_url:
            await self.simpleq.transport.delete_queue(self.dlq_name, self._dlq_url)
        self._queue_url = None
        self._dlq_url = None

    def delete_sync(self) -> None:
        """Synchronous wrapper for :meth:`delete`."""
        run_sync(self.delete())

    async def purge(self) -> None:
        """Remove all visible messages from the queue."""
        queue_url = await self.ensure_exists()
        await self.simpleq.transport.purge_queue(self.name, queue_url)

    def purge_sync(self) -> None:
        """Synchronous wrapper for :meth:`purge`."""
        run_sync(self.purge())

    async def enqueue(
        self,
        job: Job,
        *,
        delay_seconds: int = 0,
        message_group_id: str | None = None,
        deduplication_id: str | None = None,
        attributes: dict[str, str] | None = None,
    ) -> str:
        """Enqueue a single job."""
        resolved_group_id = message_group_id or routing_message_group_id(job)
        resolved_deduplication_id = deduplication_id or routing_deduplication_id(job)
        self._validate_message_options(
            delay_seconds=delay_seconds,
            message_group_id=resolved_group_id,
            deduplication_id=resolved_deduplication_id,
        )
        queue_url = await self.ensure_exists()
        prepared_job = persist_routing_metadata(
            job,
            message_group_id=resolved_group_id,
            deduplication_id=resolved_deduplication_id,
        )
        message_attributes = encode_message_attributes(attributes)
        message_id = await self.simpleq.transport.send_message(
            self.name,
            queue_url,
            message_body=prepared_job.to_message_body(),
            delay_seconds=None if self.fifo else delay_seconds,
            message_group_id=resolved_group_id,
            deduplication_id=resolved_deduplication_id,
            message_attributes=message_attributes,
        )
        self.simpleq.cost_tracker.job_enqueued(self.name)
        self.simpleq.metrics.record_enqueue(self.name)
        return str(message_id)

    async def enqueue_many(self, entries: Sequence[BatchEntry]) -> list[str]:
        """Enqueue up to 10 jobs in a single SQS batch request."""
        if len(entries) == 0:
            return []
        if len(entries) > 10:
            raise QueueValidationError("SQS batches support at most 10 entries.")

        queue_url = await self.ensure_exists()
        payloads: list[dict[str, Any]] = []
        for entry in entries:
            resolved_group_id = entry.message_group_id or routing_message_group_id(
                entry.job
            )
            resolved_deduplication_id = (
                entry.deduplication_id or routing_deduplication_id(entry.job)
            )
            self._validate_message_options(
                delay_seconds=entry.delay_seconds,
                message_group_id=resolved_group_id,
                deduplication_id=resolved_deduplication_id,
            )
            prepared_job = persist_routing_metadata(
                entry.job,
                message_group_id=resolved_group_id,
                deduplication_id=resolved_deduplication_id,
            )
            payload: dict[str, Any] = {
                "Id": uuid4().hex,
                "MessageBody": prepared_job.to_message_body(),
            }
            if not self.fifo and entry.delay_seconds:
                payload["DelaySeconds"] = entry.delay_seconds
            if resolved_group_id is not None:
                payload["MessageGroupId"] = resolved_group_id
            if resolved_deduplication_id is not None:
                payload["MessageDeduplicationId"] = resolved_deduplication_id
            if entry.attributes:
                payload["MessageAttributes"] = encode_message_attributes(
                    entry.attributes
                )
            payloads.append(payload)

        message_ids = await self.simpleq.transport.send_message_batch(
            self.name,
            queue_url,
            payloads,
        )
        self.simpleq.cost_tracker.job_enqueued(self.name, count=len(entries))
        self.simpleq.metrics.record_enqueue(self.name, count=len(entries))
        return list(message_ids)

    async def receive(
        self,
        *,
        max_messages: int | None = None,
        visibility_timeout: int | None = None,
        wait_seconds: int | None = None,
    ) -> list[Job]:
        """Receive jobs from the queue."""
        resolved_max_messages = (
            self.batch_size if max_messages is None else max_messages
        )
        resolved_wait_seconds = (
            wait_seconds if wait_seconds is not None else self.wait_seconds
        )
        self._validate_receive_options(
            max_messages=resolved_max_messages,
            wait_seconds=resolved_wait_seconds,
            visibility_timeout=visibility_timeout,
        )
        queue_url = await self.ensure_exists()
        messages = await self.simpleq.transport.receive_messages(
            self.name,
            queue_url,
            max_messages=resolved_max_messages,
            wait_seconds=resolved_wait_seconds,
            visibility_timeout=visibility_timeout,
        )
        decoded = [
            await self._decode_message(queue_url=queue_url, message=message)
            for message in messages
        ]
        return [job for job in decoded if job is not None]

    async def iter_jobs(
        self,
        *,
        limit: int | None = None,
        visibility_timeout: int | None = None,
        wait_seconds: int | None = None,
    ) -> AsyncIterator[Job]:
        """Yield jobs until the queue is empty or ``limit`` is reached."""
        yielded = 0
        while True:
            remaining = None if limit is None else limit - yielded
            if remaining == 0:
                return
            batch_size = (
                self.batch_size
                if remaining is None
                else min(self.batch_size, remaining)
            )
            jobs = await self.receive(
                max_messages=batch_size,
                visibility_timeout=visibility_timeout,
                wait_seconds=0 if wait_seconds is None else wait_seconds,
            )
            if not jobs:
                return
            for job in jobs:
                yield job
                yielded += 1

    async def ack(self, job: Job) -> None:
        """Delete a processed message."""
        if job.receipt_handle is None:
            return
        queue_url = await self.ensure_exists()
        await self.simpleq.transport.delete_message(
            self.name, queue_url, job.receipt_handle
        )

    async def change_visibility(self, job: Job, timeout_seconds: int) -> None:
        """Change the visibility timeout of a received message."""
        if job.receipt_handle is None:
            return
        if timeout_seconds < 0 or timeout_seconds > _MAX_VISIBILITY_TIMEOUT:
            raise QueueValidationError(
                f"visibility_timeout must be between 0 and {_MAX_VISIBILITY_TIMEOUT}."
            )
        queue_url = await self.ensure_exists()
        await self.simpleq.transport.change_message_visibility(
            self.name,
            queue_url,
            job.receipt_handle,
            timeout_seconds,
        )

    async def stats(self) -> QueueStats:
        """Return queue statistics."""
        queue_url = await self.ensure_exists()
        attributes = await self.simpleq.transport.get_queue_attributes(
            self.name,
            queue_url,
            [
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            ],
        )
        available = int(attributes.get("ApproximateNumberOfMessages", "0"))
        in_flight = int(attributes.get("ApproximateNumberOfMessagesNotVisible", "0"))
        delayed = int(attributes.get("ApproximateNumberOfMessagesDelayed", "0"))
        self.simpleq.metrics.record_queue_depth(self.name, available)
        return QueueStats(
            name=self.name,
            fifo=self.fifo,
            dlq_name=self.dlq_name,
            available_messages=available,
            in_flight_messages=in_flight,
            delayed_messages=delayed,
        )

    def stats_sync(self) -> QueueStats:
        """Synchronous wrapper for :meth:`stats`."""
        return run_sync(self.stats())

    async def get_dlq_jobs(self, *, limit: int = 10) -> AsyncIterator[Job]:
        """Yield jobs currently in the DLQ."""
        if self.dlq_name is None:
            raise QueueValidationError("DLQ support is not enabled for this queue.")

        dlq_queue = self._dlq_queue()
        received: list[Job] = []
        remaining = limit
        while remaining > 0:
            batch_size = min(dlq_queue.batch_size, remaining)
            jobs = await dlq_queue.receive(
                max_messages=batch_size,
                visibility_timeout=1,
                wait_seconds=0,
            )
            if not jobs:
                break
            received.extend(jobs)
            remaining -= len(jobs)
            if len(jobs) < batch_size:
                break

        try:
            for job in received:
                yield job
        finally:
            for job in received:
                await dlq_queue.change_visibility(job, 0)

    async def redrive_dlq_jobs(self, *, limit: int | None = None) -> int:
        """Move messages from the DLQ back to the primary queue."""
        if self.dlq_name is None:
            raise QueueValidationError("DLQ support is not enabled for this queue.")
        count = 0
        dlq_queue = self._dlq_queue()
        async for job in dlq_queue.iter_jobs(
            limit=limit,
            visibility_timeout=1,
            wait_seconds=0,
        ):
            requeued = job.with_attempt(0)
            await self.enqueue(
                requeued,
                message_group_id=routing_message_group_id(job),
                deduplication_id=next_deduplication_id(self, job, reason="redrive"),
                attributes=job.message_attributes,
            )
            await dlq_queue.ack(job)
            count += 1
        return count

    async def move_to_dlq(self, job: Job, *, error: str) -> None:
        """Move a failed message into the configured DLQ."""
        if self.dlq_name is None:
            await self.ack(job)
            return
        dlq_queue = self._dlq_queue()
        failed_job = job.with_attempt(job.receive_count, error=error)
        await dlq_queue.enqueue(
            failed_job,
            message_group_id=routing_message_group_id(job),
            deduplication_id=next_deduplication_id(self, job, reason="dlq"),
            attributes=job.message_attributes,
        )
        await self.ack(job)

    def _dlq_queue(self) -> Queue:
        """Return the canonical DLQ queue object for this queue."""
        if self.dlq_name is None:
            raise QueueValidationError("DLQ support is not enabled for this queue.")
        return cast(
            "Queue",
            self.simpleq.queue(
                self.dlq_name,
                fifo=self.fifo,
                dlq=False,
                max_retries=self.max_retries,
                content_based_deduplication=self.content_based_deduplication,
                visibility_timeout=self.visibility_timeout,
                wait_seconds=self.wait_seconds,
                tags=dict(self.tags) if self._tags_configured else None,
            ),
        )

    def _create_queue_attributes(
        self,
        *,
        fifo: bool,
        content_based_deduplication: bool,
        dlq_arn: str | None = None,
    ) -> dict[str, str]:
        attributes = {
            "ReceiveMessageWaitTimeSeconds": str(self.wait_seconds),
            "VisibilityTimeout": str(self.visibility_timeout),
        }
        if fifo:
            attributes["FifoQueue"] = "true"
            attributes["ContentBasedDeduplication"] = (
                "true" if content_based_deduplication else "false"
            )
        if dlq_arn is not None:
            attributes["RedrivePolicy"] = json.dumps(
                {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": self.max_retries}
            )
        return attributes

    async def _handle_malformed_message(
        self,
        *,
        queue_url: str,
        message: dict[str, Any],
        error: Exception,
    ) -> None:
        """Log and quarantine malformed messages so they do not poison polling."""
        message_id = str(message.get("MessageId", "unknown"))
        receipt_handle = message.get("ReceiptHandle")
        self.simpleq.logger.error(
            "queue_message_deserialization_failed",
            queue_name=self.name,
            message_id=message_id,
            error=str(error),
        )
        self.simpleq.metrics.record_processed(
            self.name,
            status="decode_error",
            duration_seconds=0.0,
        )
        if not isinstance(receipt_handle, str) or not receipt_handle:
            self.simpleq.logger.warning(
                "queue_malformed_message_missing_receipt_handle",
                queue_name=self.name,
                message_id=message_id,
            )
            return
        try:
            await self.simpleq.transport.delete_message(
                self.name,
                queue_url,
                receipt_handle,
            )
        except Exception as exc:
            self.simpleq.logger.error(
                "queue_malformed_message_delete_failed",
                queue_name=self.name,
                message_id=message_id,
                error=str(exc),
            )

    async def _decode_message(
        self,
        *,
        queue_url: str,
        message: dict[str, Any],
    ) -> Job | None:
        """Deserialize a received message into a Job, handling malformed payloads."""
        try:
            return Job.from_sqs_message(self.name, message)
        except Exception as exc:
            await self._handle_malformed_message(
                queue_url=queue_url,
                message=message,
                error=exc,
            )
            return None

    def _validate_message_options(
        self,
        *,
        delay_seconds: int,
        message_group_id: str | None,
        deduplication_id: str | None,
    ) -> None:
        if delay_seconds < 0 or delay_seconds > 900:
            raise QueueValidationError("delay_seconds must be between 0 and 900.")
        if self.fifo:
            if delay_seconds:
                raise QueueValidationError(
                    "FIFO queues do not support per-message delay_seconds."
                )
            if message_group_id is None:
                raise QueueValidationError("FIFO queues require a message_group_id.")
            validate_fifo_routing_identifier(
                "message_group_id",
                message_group_id,
            )
            if deduplication_id is None and not self.content_based_deduplication:
                raise QueueValidationError(
                    "FIFO queues without content-based deduplication require a deduplication_id."
                )
            validate_fifo_routing_identifier(
                "deduplication_id",
                deduplication_id,
            )

    def _validate_receive_options(
        self,
        *,
        max_messages: int,
        wait_seconds: int,
        visibility_timeout: int | None,
    ) -> None:
        if max_messages < 1 or max_messages > _MAX_RECEIVE_MESSAGES:
            raise QueueValidationError(
                f"max_messages must be between 1 and {_MAX_RECEIVE_MESSAGES}."
            )
        if wait_seconds < 0 or wait_seconds > _MAX_WAIT_SECONDS:
            raise QueueValidationError(
                f"wait_seconds must be between 0 and {_MAX_WAIT_SECONDS}."
            )
        if visibility_timeout is not None and (
            visibility_timeout < 0 or visibility_timeout > _MAX_VISIBILITY_TIMEOUT
        ):
            raise QueueValidationError(
                f"visibility_timeout must be between 0 and {_MAX_VISIBILITY_TIMEOUT}."
            )


def normalize_queue_name(name: str, *, fifo: bool) -> str:
    """Validate and normalize a queue name."""
    if not name:
        raise QueueValidationError("Queue name must be non-empty.")
    if len(name) > _MAX_QUEUE_NAME_LENGTH:
        raise QueueValidationError(
            f"Queue name must be <= {_MAX_QUEUE_NAME_LENGTH} characters."
        )

    if fifo and not name.endswith(".fifo"):
        raise QueueValidationError("FIFO queues must end with '.fifo'.")
    if not fifo and name.endswith(".fifo"):
        raise QueueValidationError("Standard queues must not end with '.fifo'.")

    base_name = name.removesuffix(".fifo") if fifo else name
    if not base_name:
        raise QueueValidationError("Queue name must include characters before '.fifo'.")
    if not _QUEUE_NAME_PATTERN.fullmatch(base_name):
        raise QueueValidationError(
            "Queue names may only contain letters, numbers, hyphens, and underscores."
        )
    return name


def string_metadata(value: Any) -> str | None:
    """Return a string metadata value or ``None``."""
    if value is None:
        return None
    return str(value)


def routing_message_group_id(job: Job) -> str | None:
    """Return the persisted FIFO message group ID for a job."""
    return first_metadata_value(
        job.metadata,
        MESSAGE_GROUP_METADATA_KEY,
        LEGACY_MESSAGE_GROUP_METADATA_KEY,
    )


def routing_deduplication_id(job: Job) -> str | None:
    """Return the persisted FIFO deduplication ID for a job."""
    return first_metadata_value(
        job.metadata,
        DEDUPLICATION_METADATA_KEY,
        LEGACY_DEDUPLICATION_METADATA_KEY,
    )


def persist_routing_metadata(
    job: Job,
    *,
    message_group_id: str | None,
    deduplication_id: str | None,
) -> Job:
    """Persist FIFO routing metadata into the serialized job body."""
    metadata = dict(job.metadata)
    changed = persist_metadata_value(
        metadata,
        MESSAGE_GROUP_METADATA_KEY,
        message_group_id,
    )
    changed = (
        persist_metadata_value(
            metadata,
            LEGACY_MESSAGE_GROUP_METADATA_KEY,
            message_group_id,
        )
        or changed
    )
    changed = (
        persist_metadata_value(
            metadata,
            DEDUPLICATION_METADATA_KEY,
            deduplication_id,
        )
        or changed
    )
    changed = (
        persist_metadata_value(
            metadata,
            LEGACY_DEDUPLICATION_METADATA_KEY,
            deduplication_id,
        )
        or changed
    )
    if not changed:
        return job
    return replace(job, metadata=metadata)


def persist_metadata_value(
    metadata: dict[str, Any],
    key: str,
    value: str | None,
) -> bool:
    """Store a string metadata value when the key is not already set."""
    if key in metadata or value is None:
        return False
    metadata[key] = value
    return True


def first_metadata_value(metadata: dict[str, Any], *keys: str) -> str | None:
    """Return the first non-null metadata value for the provided keys."""
    for key in keys:
        value = string_metadata(metadata.get(key))
        if value is not None:
            return value
    return None


def next_deduplication_id(queue: Queue, job: Job, *, reason: str) -> str | None:
    """Return a fresh FIFO deduplication ID for internal requeue operations."""
    if not queue.fifo:
        return None
    if queue.content_based_deduplication:
        return routing_deduplication_id(job)
    return f"simpleq-{reason}-{job.job_id}-{uuid4().hex}"


def validate_fifo_routing_identifier(
    name: str,
    value: str | None,
) -> None:
    """Validate an optional FIFO routing identifier."""
    if value is None:
        return
    if len(value) == 0:
        raise QueueValidationError(f"{name} must be a non-empty string when set.")
    if len(value) > _MAX_FIFO_ROUTING_ID_LENGTH:
        raise QueueValidationError(
            f"{name} must be {_MAX_FIFO_ROUTING_ID_LENGTH} characters or fewer."
        )
