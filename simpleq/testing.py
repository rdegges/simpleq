"""Testing helpers for SimpleQ.

This module provides an in-memory transport that mimics the subset of SQS
behavior needed for unit tests, examples, and local development helpers.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

_FIFO_DEDUPLICATION_WINDOW_SECONDS = 300.0


@dataclass(slots=True)
class _StoredMessage:
    """Internal representation of a queued message."""

    message_id: str
    body: str
    visible_at: float
    message_attributes: dict[str, dict[str, str]] = field(default_factory=dict)
    message_group_id: str | None = None
    deduplication_id: str | None = None
    receive_count: int = 0
    receipt_handle: str | None = None


@dataclass(slots=True)
class _StoredQueue:
    """Internal representation of an SQS queue."""

    name: str
    attributes: dict[str, str] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)
    messages: list[_StoredMessage] = field(default_factory=list)
    deduplication_cache: dict[str, tuple[float, str]] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return f"https://simpleq.test/{self.name}"

    @property
    def arn(self) -> str:
        return f"arn:aws:sqs:us-east-1:000000000000:{self.name}"


class InMemoryTransport:
    """Small in-memory SQS transport for tests and examples."""

    def __init__(self) -> None:
        self._queues: dict[str, _StoredQueue] = {}

    async def get_queue_url(self, queue_name: str) -> str | None:
        queue = self._queues.get(queue_name)
        return None if queue is None else queue.url

    async def ensure_queue(
        self,
        queue_name: str,
        *,
        attributes: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        queue = self._queues.setdefault(queue_name, _StoredQueue(name=queue_name))
        if attributes:
            queue.attributes.update(attributes)
        if tags is not None:
            queue.tags = dict(tags)
        return queue.url

    async def create_queue(
        self,
        queue_name: str,
        *,
        attributes: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        return await self.ensure_queue(queue_name, attributes=attributes, tags=tags)

    async def queue_arn(self, queue_name: str, queue_url: str) -> str:
        del queue_url
        return self._require_queue(queue_name).arn

    async def set_queue_attributes(
        self, queue_name: str, queue_url: str, attributes: dict[str, str]
    ) -> None:
        del queue_url
        self._require_queue(queue_name).attributes.update(attributes)

    async def get_queue_attributes(
        self, queue_name: str, queue_url: str, attribute_names: list[str]
    ) -> dict[str, str]:
        del queue_url
        queue = self._require_queue(queue_name)
        now = time.monotonic()
        available = 0
        in_flight = 0
        delayed = 0
        for message in queue.messages:
            if message.visible_at <= now:
                available += 1
            elif message.receive_count == 0:
                delayed += 1
            else:
                in_flight += 1

        values: dict[str, str] = dict(queue.attributes)
        values.update(
            {
                "ApproximateNumberOfMessages": str(available),
                "ApproximateNumberOfMessagesNotVisible": str(in_flight),
                "ApproximateNumberOfMessagesDelayed": str(delayed),
                "QueueArn": queue.arn,
            }
        )
        return {name: values[name] for name in attribute_names if name in values}

    async def list_queues(self, prefix: str | None = None) -> list[str]:
        names = sorted(
            name for name in self._queues if prefix is None or name.startswith(prefix)
        )
        return [self._queues[name].url for name in names]

    async def list_queue_tags(self, queue_name: str, queue_url: str) -> dict[str, str]:
        del queue_url
        return dict(self._require_queue(queue_name).tags)

    async def tag_queue(
        self,
        queue_name: str,
        queue_url: str,
        tags: dict[str, str],
    ) -> None:
        del queue_url
        self._require_queue(queue_name).tags.update(tags)

    async def untag_queue(
        self,
        queue_name: str,
        queue_url: str,
        tag_keys: list[str],
    ) -> None:
        del queue_url
        queue = self._require_queue(queue_name)
        for key in tag_keys:
            queue.tags.pop(key, None)

    async def delete_queue(self, queue_name: str, queue_url: str) -> None:
        del queue_url
        self._queues.pop(queue_name, None)

    async def purge_queue(self, queue_name: str, queue_url: str) -> None:
        del queue_url
        queue = self._require_queue(queue_name)
        queue.messages.clear()
        queue.deduplication_cache.clear()

    async def send_message(
        self,
        queue_name: str,
        queue_url: str,
        *,
        message_body: str,
        delay_seconds: int | None = None,
        message_group_id: str | None = None,
        deduplication_id: str | None = None,
        message_attributes: dict[str, dict[str, str]] | None = None,
    ) -> str:
        del queue_url
        queue = self._require_queue(queue_name)
        deduplication_key = self._deduplication_key(
            queue=queue,
            message_body=message_body,
            deduplication_id=deduplication_id,
        )
        if deduplication_key is not None:
            now = time.monotonic()
            self._purge_expired_deduplication_entries(queue, now=now)
            cached = queue.deduplication_cache.get(deduplication_key)
            if cached is not None:
                _, message_id = cached
                return message_id

        message = _StoredMessage(
            message_id=uuid4().hex,
            body=message_body,
            visible_at=time.monotonic() + max(delay_seconds or 0, 0),
            message_attributes=message_attributes or {},
            message_group_id=message_group_id,
            deduplication_id=deduplication_id,
        )
        queue.messages.append(message)
        if deduplication_key is not None:
            queue.deduplication_cache[deduplication_key] = (
                time.monotonic() + _FIFO_DEDUPLICATION_WINDOW_SECONDS,
                message.message_id,
            )
        return message.message_id

    async def send_message_batch(
        self,
        queue_name: str,
        queue_url: str,
        entries: list[dict[str, Any]],
    ) -> list[str]:
        return [
            await self.send_message(
                queue_name,
                queue_url,
                message_body=str(entry["MessageBody"]),
                delay_seconds=int(entry.get("DelaySeconds", 0)),
                message_group_id=entry.get("MessageGroupId"),
                deduplication_id=entry.get("MessageDeduplicationId"),
                message_attributes=entry.get("MessageAttributes"),
            )
            for entry in entries
        ]

    async def receive_messages(
        self,
        queue_name: str,
        queue_url: str,
        *,
        max_messages: int,
        wait_seconds: int,
        visibility_timeout: int | None,
    ) -> list[dict[str, Any]]:
        del queue_url, wait_seconds
        queue = self._require_queue(queue_name)
        now = time.monotonic()
        timeout = visibility_timeout
        if timeout is None:
            timeout = int(queue.attributes.get("VisibilityTimeout", "30"))
        received: list[dict[str, Any]] = []
        blocked_groups = self._blocked_fifo_groups(queue, now=now)
        selected_groups: set[str] = set()
        for message in queue.messages:
            if len(received) >= max_messages:
                break
            if message.visible_at > now:
                continue
            if (
                message.message_group_id is not None
                and message.message_group_id in blocked_groups
                and message.message_group_id not in selected_groups
            ):
                continue
            message.receive_count += 1
            message.receipt_handle = uuid4().hex
            message.visible_at = now + timeout
            if message.message_group_id is not None:
                selected_groups.add(message.message_group_id)
            attributes = {"ApproximateReceiveCount": str(message.receive_count)}
            if message.message_group_id is not None:
                attributes["MessageGroupId"] = message.message_group_id
            if message.deduplication_id is not None:
                attributes["MessageDeduplicationId"] = message.deduplication_id
            received.append(
                {
                    "Body": message.body,
                    "ReceiptHandle": message.receipt_handle,
                    "MessageId": message.message_id,
                    "Attributes": attributes,
                    "MessageAttributes": message.message_attributes,
                }
            )
        return received

    async def delete_message(
        self, queue_name: str, queue_url: str, receipt_handle: str
    ) -> None:
        del queue_url
        queue = self._require_queue(queue_name)
        queue.messages = [
            message
            for message in queue.messages
            if message.receipt_handle != receipt_handle
        ]

    async def change_message_visibility(
        self,
        queue_name: str,
        queue_url: str,
        receipt_handle: str,
        timeout_seconds: int,
    ) -> None:
        del queue_url
        queue = self._require_queue(queue_name)
        for message in queue.messages:
            if message.receipt_handle == receipt_handle:
                message.visible_at = time.monotonic() + timeout_seconds
                return

    def _require_queue(self, queue_name: str) -> _StoredQueue:
        queue = self._queues.get(queue_name)
        if queue is None:
            raise KeyError(f"Queue '{queue_name}' is not defined.")
        return queue

    @staticmethod
    def _purge_expired_deduplication_entries(queue: _StoredQueue, *, now: float) -> None:
        queue.deduplication_cache = {
            key: value
            for key, value in queue.deduplication_cache.items()
            if value[0] > now
        }

    @staticmethod
    def _deduplication_key(
        *,
        queue: _StoredQueue,
        message_body: str,
        deduplication_id: str | None,
    ) -> str | None:
        if queue.attributes.get("FifoQueue") != "true":
            return None
        if deduplication_id:
            return f"dedup:{deduplication_id}"
        if queue.attributes.get("ContentBasedDeduplication") == "true":
            content_hash = hashlib.sha256(message_body.encode("utf-8")).hexdigest()
            return f"body:{content_hash}"
        return None

    @staticmethod
    def _blocked_fifo_groups(queue: _StoredQueue, *, now: float) -> set[str]:
        if queue.attributes.get("FifoQueue") != "true":
            return set()
        return {
            message.message_group_id
            for message in queue.messages
            if message.message_group_id is not None and message.visible_at > now
        }
