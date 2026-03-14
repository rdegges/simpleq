"""SQS queue abstraction for SimpleQ."""

from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypeVar
from uuid import uuid4

from simpleq._sync import run_sync
from simpleq.exceptions import QueueNotFoundError, QueueValidationError
from simpleq.job import (
    DEDUPLICATION_METADATA_KEY,
    LEGACY_DEDUPLICATION_METADATA_KEY,
    LEGACY_MESSAGE_GROUP_METADATA_KEY,
    MESSAGE_GROUP_METADATA_KEY,
    Job,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence

    from simpleq.protocols import QueueAppProtocol
    from simpleq.serializers import JSONValue

_QUEUE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_MESSAGE_ATTRIBUTE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_QUEUE_NAME_LENGTH = 80
_MAX_RECEIVE_MESSAGES = 10
_MAX_WAIT_SECONDS = 20
_MAX_VISIBILITY_TIMEOUT = 43_200
_MAX_MESSAGE_ATTRIBUTES = 10
_MAX_MESSAGE_ATTRIBUTE_NAME_LENGTH = 256
_MAX_MESSAGE_ATTRIBUTE_VALUE_BYTES = 1_048_576
_MAX_MESSAGE_SIZE_BYTES = 1_048_576
_MAX_FIFO_ROUTING_ID_LENGTH = 128
_ALLOWED_FIFO_ROUTING_ID_CHARACTERS = frozenset(
    string.ascii_letters + string.digits + r"""!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~"""
)
_MAX_RECEIVE_REQUEST_ATTEMPT_ID_LENGTH = 128
_MAX_DLQ_MAX_RECEIVE_COUNT = 1000
_MAX_QUEUE_TAGS = 50
_MAX_TAG_KEY_LENGTH = 128
_MAX_TAG_VALUE_LENGTH = 256
_MISSING_QUEUE_ERROR_CODES = {
    "AWS.SimpleQueueService.NonExistentQueue",
    "QueueDoesNotExist",
}
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class QueueStats:
    """High-level queue statistics."""

    name: str
    fifo: bool
    dlq_name: str | None
    available_messages: int
    in_flight_messages: int
    delayed_messages: int
    dlq_available_messages: int | None = None
    dlq_in_flight_messages: int | None = None
    dlq_delayed_messages: int | None = None


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
        if key.startswith(".") or key.endswith("."):
            raise QueueValidationError(
                "message attribute names must not start or end with a period."
            )
        if ".." in key:
            raise QueueValidationError(
                "message attribute names must not contain consecutive periods."
            )
        lowered_key = key.lower()
        if lowered_key.startswith("aws.") or lowered_key.startswith("amazon."):
            raise QueueValidationError(
                "message attribute names must not start with 'AWS.' or 'Amazon.'."
            )
        if not isinstance(value, str):
            raise QueueValidationError("message attribute values must be strings.")
        if len(value.encode("utf-8")) > _MAX_MESSAGE_ATTRIBUTE_VALUE_BYTES:
            raise QueueValidationError(
                "message attribute values must be at most 1048576 bytes."
            )
    return {
        key: {"DataType": "String", "StringValue": value}
        for key, value in attributes.items()
    }


def message_payload_size_bytes(
    message_body: str,
    message_attributes: dict[str, dict[str, str]],
) -> int:
    """Return the SQS payload size contributed by a message body and attributes."""
    size = len(message_body.encode("utf-8"))
    for key, attribute in message_attributes.items():
        size += len(key.encode("utf-8"))
        size += len(str(attribute.get("DataType", "")).encode("utf-8"))
        size += len(str(attribute.get("StringValue", "")).encode("utf-8"))
    return size


def validate_message_payload_size(
    message_body: str,
    message_attributes: dict[str, dict[str, str]],
) -> int:
    """Validate a single SQS message payload against the queue size limit."""
    size = message_payload_size_bytes(message_body, message_attributes)
    if size > _MAX_MESSAGE_SIZE_BYTES:
        raise QueueValidationError(
            "SQS message payloads must be at most 1048576 bytes including "
            "message attributes."
        )
    return size


class Queue:
    """High-level queue abstraction built on Amazon SQS."""

    def __init__(
        self,
        simpleq: QueueAppProtocol,
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
        self.tags = validate_queue_tags(tags)
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
        await self._delete_queue_with_stale_recovery(
            queue_name=self.name,
            cached_url=self._queue_url,
        )

        if self.dlq_name is not None:
            await self._delete_queue_with_stale_recovery(
                queue_name=self.dlq_name,
                cached_url=self._dlq_url,
            )

        invalidate = getattr(self.simpleq.transport, "invalidate_queue_url", None)
        if callable(invalidate):
            invalidate(self.name)
            if self.dlq_name is not None:
                invalidate(self.dlq_name)
        self._queue_url = None
        self._dlq_url = None

    def delete_sync(self) -> None:
        """Synchronous wrapper for :meth:`delete`."""
        run_sync(self.delete())

    async def purge(self) -> None:
        """Remove all visible messages from the queue."""
        await self._with_refreshed_queue_url(
            "purge_queue",
            lambda queue_url: self.simpleq.transport.purge_queue(self.name, queue_url),
        )

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
        resolved_group_id = (
            message_group_id
            if message_group_id is not None
            else routing_message_group_id(job)
        )
        resolved_deduplication_id = (
            deduplication_id
            if deduplication_id is not None
            else routing_deduplication_id(job)
        )
        self._validate_message_options(
            delay_seconds=delay_seconds,
            message_group_id=resolved_group_id,
            deduplication_id=resolved_deduplication_id,
        )
        prepared_job = persist_routing_metadata(
            job,
            message_group_id=resolved_group_id,
            deduplication_id=resolved_deduplication_id,
        )
        message_body = prepared_job.to_message_body()
        message_attributes = encode_message_attributes(attributes)
        validate_message_payload_size(message_body, message_attributes)
        message_id = await self._with_refreshed_queue_url(
            "send_message",
            lambda queue_url: self.simpleq.transport.send_message(
                self.name,
                queue_url,
                message_body=message_body,
                delay_seconds=None if self.fifo else delay_seconds,
                message_group_id=resolved_group_id,
                deduplication_id=resolved_deduplication_id,
                message_attributes=message_attributes,
            ),
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

        payloads: list[dict[str, object]] = []
        total_payload_size = 0
        for entry in entries:
            resolved_group_id = (
                entry.message_group_id
                if entry.message_group_id is not None
                else routing_message_group_id(entry.job)
            )
            resolved_deduplication_id = (
                entry.deduplication_id
                if entry.deduplication_id is not None
                else routing_deduplication_id(entry.job)
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
            message_body = prepared_job.to_message_body()
            message_attributes = encode_message_attributes(entry.attributes)
            total_payload_size += validate_message_payload_size(
                message_body,
                message_attributes,
            )
            payload: dict[str, object] = {
                "Id": uuid4().hex,
                "MessageBody": message_body,
            }
            if not self.fifo and entry.delay_seconds:
                payload["DelaySeconds"] = entry.delay_seconds
            if resolved_group_id is not None:
                payload["MessageGroupId"] = resolved_group_id
            if resolved_deduplication_id is not None:
                payload["MessageDeduplicationId"] = resolved_deduplication_id
            if message_attributes:
                payload["MessageAttributes"] = message_attributes
            payloads.append(payload)

        if total_payload_size > _MAX_MESSAGE_SIZE_BYTES:
            raise QueueValidationError(
                "SQS batch payloads must total at most 1048576 bytes across all "
                "messages."
            )

        message_ids = await self._with_refreshed_queue_url(
            "send_message_batch",
            lambda queue_url: self.simpleq.transport.send_message_batch(
                self.name,
                queue_url,
                payloads,
            ),
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
        receive_request_attempt_id: str | None = None,
    ) -> list[Job]:
        """Receive jobs from the queue.

        ``receive_request_attempt_id`` is FIFO-only and maps to SQS
        ``ReceiveRequestAttemptId`` for idempotent receive retries.
        """
        resolved_max_messages = (
            self.batch_size if max_messages is None else max_messages
        )
        resolved_wait_seconds = (
            wait_seconds if wait_seconds is not None else self.wait_seconds
        )
        resolved_receive_request_attempt_id = normalize_receive_request_attempt_id(
            receive_request_attempt_id
        )
        self._validate_receive_options(
            max_messages=resolved_max_messages,
            wait_seconds=resolved_wait_seconds,
            visibility_timeout=visibility_timeout,
            receive_request_attempt_id=resolved_receive_request_attempt_id,
        )
        queue_url, messages = await self._with_refreshed_queue_url(
            "receive_messages",
            lambda queue_url: self._receive_raw_messages(
                queue_url,
                max_messages=resolved_max_messages,
                wait_seconds=resolved_wait_seconds,
                visibility_timeout=visibility_timeout,
                receive_request_attempt_id=resolved_receive_request_attempt_id,
            ),
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
        validate_positive_limit("limit", limit)
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
        receipt_handle = job.receipt_handle
        if not has_usable_receipt_handle(receipt_handle):
            return
        assert receipt_handle is not None
        await self._with_refreshed_queue_url(
            "delete_message",
            lambda queue_url: self.simpleq.transport.delete_message(
                self.name, queue_url, receipt_handle
            ),
        )

    async def change_visibility(self, job: Job, timeout_seconds: int) -> None:
        """Change the visibility timeout of a received message."""
        receipt_handle = job.receipt_handle
        if not has_usable_receipt_handle(receipt_handle):
            return
        assert receipt_handle is not None
        if not is_strict_int(timeout_seconds):
            raise QueueValidationError("visibility_timeout must be an integer.")
        if timeout_seconds < 0 or timeout_seconds > _MAX_VISIBILITY_TIMEOUT:
            raise QueueValidationError(
                f"visibility_timeout must be between 0 and {_MAX_VISIBILITY_TIMEOUT}."
            )
        await self._with_refreshed_queue_url(
            "change_message_visibility",
            lambda queue_url: self.simpleq.transport.change_message_visibility(
                self.name,
                queue_url,
                receipt_handle,
                timeout_seconds,
            ),
        )

    async def stats(self) -> QueueStats:
        """Return queue statistics."""
        available, in_flight, delayed = await self._with_refreshed_queue_url(
            "get_queue_attributes",
            lambda queue_url: self._stats_for_queue(
                self.name,
                queue_url,
            ),
        )
        self.simpleq.metrics.record_queue_depth(self.name, available)
        dlq_available: int | None = None
        dlq_in_flight: int | None = None
        dlq_delayed: int | None = None
        if self.dlq_name is not None:
            dlq_queue = self._dlq_queue()
            (
                dlq_available_now,
                dlq_in_flight_now,
                dlq_delayed_now,
            ) = await dlq_queue._with_refreshed_queue_url(
                "get_queue_attributes",
                lambda dlq_url: dlq_queue._stats_for_queue(
                    dlq_queue.name,
                    dlq_url,
                ),
            )
            self.simpleq.metrics.record_queue_depth(dlq_queue.name, dlq_available_now)
            dlq_available = dlq_available_now
            dlq_in_flight = dlq_in_flight_now
            dlq_delayed = dlq_delayed_now
        return QueueStats(
            name=self.name,
            fifo=self.fifo,
            dlq_name=self.dlq_name,
            available_messages=available,
            in_flight_messages=in_flight,
            delayed_messages=delayed,
            dlq_available_messages=dlq_available,
            dlq_in_flight_messages=dlq_in_flight,
            dlq_delayed_messages=dlq_delayed,
        )

    def stats_sync(self) -> QueueStats:
        """Synchronous wrapper for :meth:`stats`."""
        return run_sync(self.stats())

    async def get_dlq_jobs(self, *, limit: int = 10) -> AsyncIterator[Job]:
        """Yield jobs currently in the DLQ."""
        if self.dlq_name is None:
            raise QueueValidationError("DLQ support is not enabled for this queue.")
        validate_positive_limit("limit", limit)

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
                await self._reset_dlq_visibility(dlq_queue, job)

    async def redrive_dlq_jobs(self, *, limit: int | None = None) -> int:
        """Move messages from the DLQ back to the primary queue."""
        if self.dlq_name is None:
            raise QueueValidationError("DLQ support is not enabled for this queue.")
        validate_positive_limit("limit", limit)
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
        return self.simpleq.queue(
            self.dlq_name,
            fifo=self.fifo,
            dlq=False,
            max_retries=self.max_retries,
            content_based_deduplication=self.content_based_deduplication,
            visibility_timeout=self.visibility_timeout,
            wait_seconds=self.wait_seconds,
            tags=dict(self.tags) if self._tags_configured else None,
        )

    def _create_queue_attributes(
        self,
        *,
        fifo: bool,
        content_based_deduplication: bool,
        dlq_arn: str | None = None,
    ) -> dict[str, str]:
        attributes = {
            "MaximumMessageSize": str(_MAX_MESSAGE_SIZE_BYTES),
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
        message: dict[str, object],
        error: Exception,
    ) -> None:
        """Log and quarantine malformed messages so they do not poison polling."""
        message_id = str(message.get("MessageId", "unknown"))
        raw_receipt_handle = message.get("ReceiptHandle")
        receipt_handle = (
            raw_receipt_handle if isinstance(raw_receipt_handle, str) else None
        )
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
        self.simpleq.cost_tracker.job_decode_failed(self.name)
        if not has_usable_receipt_handle(receipt_handle):
            self.simpleq.logger.warning(
                "queue_malformed_message_missing_receipt_handle",
                queue_name=self.name,
                message_id=message_id,
            )
            return
        assert receipt_handle is not None
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
        message: dict[str, object],
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

    async def _stats_for_queue(
        self,
        queue_name: str,
        queue_url: str,
    ) -> tuple[int, int, int]:
        """Fetch the standard message-count attributes for a queue."""
        attributes = await self.simpleq.transport.get_queue_attributes(
            queue_name,
            queue_url,
            [
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            ],
        )
        return (
            self._parse_queue_metric(
                queue_name,
                "ApproximateNumberOfMessages",
                attributes.get("ApproximateNumberOfMessages"),
            ),
            self._parse_queue_metric(
                queue_name,
                "ApproximateNumberOfMessagesNotVisible",
                attributes.get("ApproximateNumberOfMessagesNotVisible"),
            ),
            self._parse_queue_metric(
                queue_name,
                "ApproximateNumberOfMessagesDelayed",
                attributes.get("ApproximateNumberOfMessagesDelayed"),
            ),
        )

    def _parse_queue_metric(
        self,
        queue_name: str,
        attribute_name: str,
        value: object,
    ) -> int:
        """Parse an integer queue metric while tolerating malformed values."""
        if value is None:
            return 0
        if isinstance(value, bool):
            self.simpleq.logger.warning(
                "queue_stats_metric_parse_failed",
                queue_name=queue_name,
                attribute_name=attribute_name,
                value=str(value),
            )
            return 0
        try:
            parsed = value if isinstance(value, int) else int(str(value))
        except (TypeError, ValueError):
            self.simpleq.logger.warning(
                "queue_stats_metric_parse_failed",
                queue_name=queue_name,
                attribute_name=attribute_name,
                value=str(value),
            )
            return 0
        if parsed < 0:
            self.simpleq.logger.warning(
                "queue_stats_metric_negative_value",
                queue_name=queue_name,
                attribute_name=attribute_name,
                value=parsed,
            )
            return 0
        return parsed

    async def _receive_raw_messages(
        self,
        queue_url: str,
        *,
        max_messages: int,
        wait_seconds: int,
        visibility_timeout: int | None,
        receive_request_attempt_id: str | None,
    ) -> tuple[str, list[dict[str, object]]]:
        messages = await self.simpleq.transport.receive_messages(
            self.name,
            queue_url,
            max_messages=max_messages,
            wait_seconds=wait_seconds,
            visibility_timeout=visibility_timeout,
            receive_request_attempt_id=receive_request_attempt_id,
        )
        return queue_url, messages

    async def _queue_url_for_delete(
        self,
        queue_name: str,
        cached_url: str | None,
    ) -> str | None:
        """Resolve a queue URL for delete operations without creating a queue."""
        if cached_url is not None:
            return cached_url
        get_queue_url = getattr(self.simpleq.transport, "get_queue_url", None)
        if callable(get_queue_url):
            try:
                resolved_url = await get_queue_url(queue_name)
            except Exception as exc:
                if is_missing_queue_error(exc):
                    return None
                raise
            if resolved_url is None or isinstance(resolved_url, str):
                return resolved_url
            raise QueueValidationError(
                "transport.get_queue_url must return a string or None."
            )
        return None

    async def _delete_queue_with_stale_recovery(
        self,
        *,
        queue_name: str,
        cached_url: str | None,
    ) -> None:
        """Delete queue_name, retrying once when a stale URL is detected."""
        queue_url = await self._queue_url_for_delete(queue_name, cached_url)
        if queue_url is None:
            return
        try:
            await self.simpleq.transport.delete_queue(queue_name, queue_url)
            return
        except Exception as exc:
            if not is_missing_queue_error(exc):
                raise

        invalidate = getattr(self.simpleq.transport, "invalidate_queue_url", None)
        if callable(invalidate):
            invalidate(queue_name)

        refreshed_url = await self._queue_url_for_delete(queue_name, None)
        if refreshed_url is None:
            return
        try:
            await self.simpleq.transport.delete_queue(queue_name, refreshed_url)
        except Exception as exc:
            if not is_missing_queue_error(exc):
                raise

    async def _with_refreshed_queue_url(
        self,
        operation: str,
        call: Callable[[str], Awaitable[T]],
    ) -> T:
        queue_url = await self.ensure_exists()
        try:
            return await call(queue_url)
        except Exception as exc:
            if not is_missing_queue_error(exc):
                raise
            self.simpleq.logger.warning(
                "queue_url_stale_retry",
                queue_name=self.name,
                operation=operation,
                error=str(exc),
            )
            self._queue_url = None
            invalidate = getattr(self.simpleq.transport, "invalidate_queue_url", None)
            if callable(invalidate):
                invalidate(self.name)
            refreshed_url = await self.ensure_exists()
            return await call(refreshed_url)

    async def _reset_dlq_visibility(self, dlq_queue: Queue, job: Job) -> None:
        """Best-effort visibility reset for DLQ inspection helpers."""
        try:
            await dlq_queue.change_visibility(job, 0)
        except Exception as exc:
            self.simpleq.logger.warning(
                "queue_dlq_visibility_reset_failed",
                queue_name=dlq_queue.name,
                job_id=job.job_id,
                error=str(exc),
            )

    def _validate_message_options(
        self,
        *,
        delay_seconds: int,
        message_group_id: str | None,
        deduplication_id: str | None,
    ) -> None:
        if not is_strict_int(delay_seconds):
            raise QueueValidationError("delay_seconds must be an integer.")
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
        else:
            if message_group_id is not None:
                raise QueueValidationError(
                    "Standard queues do not support message_group_id."
                )
            if deduplication_id is not None:
                raise QueueValidationError(
                    "Standard queues do not support deduplication_id."
                )

    def _validate_receive_options(
        self,
        *,
        max_messages: int,
        wait_seconds: int,
        visibility_timeout: int | None,
        receive_request_attempt_id: str | None = None,
    ) -> None:
        if not is_strict_int(max_messages):
            raise QueueValidationError("max_messages must be an integer.")
        if max_messages < 1 or max_messages > _MAX_RECEIVE_MESSAGES:
            raise QueueValidationError(
                f"max_messages must be between 1 and {_MAX_RECEIVE_MESSAGES}."
            )
        if not is_strict_int(wait_seconds):
            raise QueueValidationError("wait_seconds must be an integer.")
        if wait_seconds < 0 or wait_seconds > _MAX_WAIT_SECONDS:
            raise QueueValidationError(
                f"wait_seconds must be between 0 and {_MAX_WAIT_SECONDS}."
            )
        if visibility_timeout is not None:
            if not is_strict_int(visibility_timeout):
                raise QueueValidationError("visibility_timeout must be an integer.")
            if visibility_timeout < 0 or visibility_timeout > _MAX_VISIBILITY_TIMEOUT:
                raise QueueValidationError(
                    f"visibility_timeout must be between 0 and {_MAX_VISIBILITY_TIMEOUT}."
                )
        if receive_request_attempt_id is not None:
            normalized_attempt_id = normalize_receive_request_attempt_id(
                receive_request_attempt_id
            )
            if normalized_attempt_id is None:
                raise QueueValidationError(
                    "receive_request_attempt_id must be a non-empty string."
                )
            if not self.fifo:
                raise QueueValidationError(
                    "receive_request_attempt_id is only supported for FIFO queues."
                )
            validate_receive_request_attempt_id(normalized_attempt_id)


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


def validate_queue_tags(tags: dict[str, str] | None) -> dict[str, str]:
    """Validate queue tags against SQS limits and return a stable copy."""
    if tags is None:
        return {}
    if len(tags) > _MAX_QUEUE_TAGS:
        raise QueueValidationError(
            f"queue tags support at most {_MAX_QUEUE_TAGS} entries."
        )

    copied_tags: dict[str, str] = {}
    for key, value in tags.items():
        if not isinstance(key, str) or not key:
            raise QueueValidationError("queue tag keys must be non-empty strings.")
        if key.lower().startswith("aws:"):
            raise QueueValidationError("queue tag keys must not start with 'aws:'.")
        if len(key) > _MAX_TAG_KEY_LENGTH:
            raise QueueValidationError(
                f"queue tag keys must be {_MAX_TAG_KEY_LENGTH} characters or fewer."
            )
        if not isinstance(value, str):
            raise QueueValidationError("queue tag values must be strings.")
        if len(value) > _MAX_TAG_VALUE_LENGTH:
            raise QueueValidationError(
                f"queue tag values must be {_MAX_TAG_VALUE_LENGTH} characters or fewer."
            )
        copied_tags[key] = value
    return copied_tags


def validate_positive_limit(name: str, value: int | None) -> None:
    """Validate optional ``limit`` style arguments."""
    if value is None:
        return
    if not is_strict_int(value):
        raise QueueValidationError(f"{name} must be an integer.")
    if value < 1:
        raise QueueValidationError(f"{name} must be at least 1.")


def normalize_receive_request_attempt_id(value: str | None) -> str | None:
    """Normalize FIFO receive request attempt IDs from user input."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise QueueValidationError("receive_request_attempt_id must be a string.")
    normalized = value.strip()
    if not normalized:
        raise QueueValidationError(
            "receive_request_attempt_id must be a non-empty string."
        )
    return normalized


def validate_receive_request_attempt_id(value: str | None) -> None:
    """Validate a normalized FIFO receive request attempt ID."""
    if value is None:
        return
    if len(value) > _MAX_RECEIVE_REQUEST_ATTEMPT_ID_LENGTH:
        raise QueueValidationError(
            "receive_request_attempt_id must be 128 characters or fewer."
        )
    if any(char not in _ALLOWED_FIFO_ROUTING_ID_CHARACTERS for char in value):
        raise QueueValidationError(
            "receive_request_attempt_id may only contain letters, numbers, and punctuation."
        )


def has_usable_receipt_handle(receipt_handle: str | None) -> bool:
    """Return whether a message receipt handle is present and non-blank."""
    return isinstance(receipt_handle, str) and bool(receipt_handle.strip())


def string_metadata(value: object) -> str | None:
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
    metadata: dict[str, JSONValue],
    key: str,
    value: str | None,
) -> bool:
    """Store the current string metadata value for a reserved routing key."""
    if value is None:
        return False
    string_value = str(value)
    if metadata.get(key) == string_value:
        return False
    metadata[key] = string_value
    return True


def first_metadata_value(
    metadata: Mapping[str, JSONValue],
    *keys: str,
) -> str | None:
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
    return f"simpleq-{reason}-{job.job_id}-{uuid4().hex}"


def validate_fifo_routing_identifier(
    name: str,
    value: str | None,
) -> None:
    """Validate an optional FIFO routing identifier."""
    if value is None:
        return
    if not isinstance(value, str):
        raise QueueValidationError(f"{name} must be a string when set.")
    if len(value.strip()) == 0:
        raise QueueValidationError(f"{name} must be a non-empty string when set.")
    if len(value) > _MAX_FIFO_ROUTING_ID_LENGTH:
        raise QueueValidationError(
            f"{name} must be {_MAX_FIFO_ROUTING_ID_LENGTH} characters or fewer."
        )
    if any(char not in _ALLOWED_FIFO_ROUTING_ID_CHARACTERS for char in value):
        raise QueueValidationError(
            f"{name} may only contain letters, numbers, and punctuation."
        )


def is_strict_int(value: object) -> bool:
    """Return whether ``value`` is an integer but not a boolean."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_missing_queue_error(exc: Exception) -> bool:
    """Return whether an exception represents a missing queue."""
    if isinstance(exc, QueueNotFoundError):
        return True
    if isinstance(exc, KeyError):
        text = str(exc)
        return text.startswith("\"Queue '") and text.endswith(' is not defined."')
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error")
    if not isinstance(error, dict):
        return False
    code = error.get("Code")
    return isinstance(code, str) and code in _MISSING_QUEUE_ERROR_CODES
