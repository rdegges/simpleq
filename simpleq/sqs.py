"""Low-level SQS operations for SimpleQ."""

from __future__ import annotations

import asyncio
import ipaddress
import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError

from simpleq.exceptions import QueueBatchError, QueueError, QueueNotFoundError

if TYPE_CHECKING:
    from collections.abc import Callable

    from simpleq.config import SimpleQConfig
    from simpleq.observability import CostTracker, OperationName

_MISSING_QUEUE_ERROR_CODES = {
    "AWS.SimpleQueueService.NonExistentQueue",
    "QueueDoesNotExist",
}


class SQSClient:
    """Thin async wrapper around the boto3 SQS client."""

    def __init__(
        self,
        config: SimpleQConfig,
        cost_tracker: CostTracker,
        *,
        session_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.config = config
        self.cost_tracker = cost_tracker
        self._session_factory = session_factory or boto3.session.Session
        self._client: Any | None = None
        self._queue_urls: dict[str, str] = {}

    @property
    def client(self) -> Any:
        """Return the lazily-created boto3 SQS client."""
        if self._client is None:
            session_or_client = self._session_factory()
            if hasattr(session_or_client, "client"):
                client_kwargs: dict[str, Any] = {
                    "region_name": self.config.region,
                    "endpoint_url": self.config.endpoint_url,
                }
                if uses_local_credentials(self.config.endpoint_url):
                    client_kwargs["aws_access_key_id"] = os.getenv(
                        "AWS_ACCESS_KEY_ID", "test"
                    )
                    client_kwargs["aws_secret_access_key"] = os.getenv(
                        "AWS_SECRET_ACCESS_KEY", "test"
                    )
                    if token := os.getenv("AWS_SESSION_TOKEN"):
                        client_kwargs["aws_session_token"] = token
                self._client = session_or_client.client("sqs", **client_kwargs)
            else:
                self._client = session_or_client
        return self._client

    async def _call(
        self,
        queue_name: str,
        operation: OperationName,
        func_name: str,
        /,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.cost_tracker.track_request(queue_name, operation)
        func = getattr(self.client, func_name)
        return await asyncio.to_thread(func, **kwargs)

    async def get_queue_url(self, queue_name: str) -> str | None:
        """Return the queue URL if the queue exists."""
        if queue_name in self._queue_urls:
            return self._queue_urls[queue_name]

        try:
            response = await self._call(
                queue_name,
                "get_queue_url",
                "get_queue_url",
                QueueName=queue_name,
            )
        except ClientError as exc:
            error_code = client_error_code(exc)
            if error_code in _MISSING_QUEUE_ERROR_CODES:
                return None
            raise

        url = response_non_empty_string(
            response,
            "QueueUrl",
            queue_name=queue_name,
            operation="get_queue_url",
        )
        self._queue_urls[queue_name] = url
        return url

    async def create_queue(
        self,
        queue_name: str,
        *,
        attributes: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        """Create an SQS queue and cache its URL."""
        response = await self._call(
            queue_name,
            "create_queue",
            "create_queue",
            QueueName=queue_name,
            Attributes=attributes or {},
            tags=tags or {},
        )
        url = response_non_empty_string(
            response,
            "QueueUrl",
            queue_name=queue_name,
            operation="create_queue",
        )
        self._queue_urls[queue_name] = url
        return url

    async def ensure_queue(
        self,
        queue_name: str,
        *,
        attributes: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        """Return a queue URL, creating the queue if necessary."""
        if url := await self.get_queue_url(queue_name):
            if attributes:
                await self.set_queue_attributes(queue_name, url, attributes)
            if tags is not None:
                await self.reconcile_queue_tags(queue_name, url, tags)
            return url
        return await self.create_queue(queue_name, attributes=attributes, tags=tags)

    async def set_queue_attributes(
        self, queue_name: str, queue_url: str, attributes: dict[str, str]
    ) -> None:
        """Set queue attributes."""
        await self._call(
            queue_name,
            "set_queue_attributes",
            "set_queue_attributes",
            QueueUrl=queue_url,
            Attributes=attributes,
        )

    async def get_queue_attributes(
        self, queue_name: str, queue_url: str, attribute_names: list[str]
    ) -> dict[str, str]:
        """Fetch selected queue attributes."""
        response = await self._call(
            queue_name,
            "get_queue_attributes",
            "get_queue_attributes",
            QueueUrl=queue_url,
            AttributeNames=attribute_names,
        )
        attributes = response_mapping(
            response,
            "Attributes",
            queue_name=queue_name,
            operation="get_queue_attributes",
        )
        return {str(key): str(value) for key, value in attributes.items()}

    async def list_queues(self, prefix: str | None = None) -> list[str]:
        """List queue URLs, optionally by prefix."""
        queue_urls: list[str] = []
        next_token: str | None = None
        seen_tokens: set[str] = set()

        while True:
            request: dict[str, Any] = {
                "QueueNamePrefix": prefix or "",
                "MaxResults": 1000,
            }
            if next_token is not None:
                request["NextToken"] = next_token

            response = await self._call(
                prefix or "global",
                "list_queues",
                "list_queues",
                **request,
            )
            queue_urls.extend(str(item) for item in response.get("QueueUrls", []))

            raw_token = response.get("NextToken")
            if raw_token is None:
                break
            token = str(raw_token).strip()
            if not token or token in seen_tokens:
                break
            seen_tokens.add(token)
            next_token = token

        return queue_urls

    async def list_queue_tags(self, queue_name: str, queue_url: str) -> dict[str, str]:
        """Return the current queue tags."""
        response = await self._call(
            queue_name,
            "list_queue_tags",
            "list_queue_tags",
            QueueUrl=queue_url,
        )
        return dict(response.get("Tags", {}))

    async def tag_queue(
        self,
        queue_name: str,
        queue_url: str,
        tags: dict[str, str],
    ) -> None:
        """Add or update queue tags."""
        await self._call(
            queue_name,
            "tag_queue",
            "tag_queue",
            QueueUrl=queue_url,
            Tags=tags,
        )

    async def untag_queue(
        self,
        queue_name: str,
        queue_url: str,
        tag_keys: list[str],
    ) -> None:
        """Remove queue tags by key."""
        await self._call(
            queue_name,
            "untag_queue",
            "untag_queue",
            QueueUrl=queue_url,
            TagKeys=tag_keys,
        )

    async def reconcile_queue_tags(
        self,
        queue_name: str,
        queue_url: str,
        desired_tags: dict[str, str],
    ) -> None:
        """Reconcile an existing queue's tags to the desired set."""
        current_tags = await self.list_queue_tags(queue_name, queue_url)
        tags_to_add = {
            key: value
            for key, value in desired_tags.items()
            if current_tags.get(key) != value
        }
        tag_keys_to_remove = sorted(
            key for key in current_tags if key not in desired_tags
        )
        if tags_to_add:
            await self.tag_queue(queue_name, queue_url, tags_to_add)
        if tag_keys_to_remove:
            await self.untag_queue(queue_name, queue_url, tag_keys_to_remove)

    async def delete_queue(self, queue_name: str, queue_url: str) -> None:
        """Delete a queue and drop its cached URL."""
        await self._call(
            queue_name,
            "delete_queue",
            "delete_queue",
            QueueUrl=queue_url,
        )
        self._queue_urls.pop(queue_name, None)

    async def purge_queue(self, queue_name: str, queue_url: str) -> None:
        """Purge all visible messages from a queue."""
        await self._call(
            queue_name,
            "purge_queue",
            "purge_queue",
            QueueUrl=queue_url,
        )

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
        """Send a single message and return the SQS message ID."""
        kwargs: dict[str, Any] = {
            "QueueUrl": queue_url,
            "MessageBody": message_body,
        }
        if delay_seconds is not None:
            kwargs["DelaySeconds"] = delay_seconds
        if message_group_id is not None:
            kwargs["MessageGroupId"] = message_group_id
        if deduplication_id is not None:
            kwargs["MessageDeduplicationId"] = deduplication_id
        if message_attributes:
            kwargs["MessageAttributes"] = message_attributes

        response = await self._call(
            queue_name,
            "send_message",
            "send_message",
            **kwargs,
        )
        return response_non_empty_string(
            response,
            "MessageId",
            queue_name=queue_name,
            operation="send_message",
        )

    async def send_message_batch(
        self,
        queue_name: str,
        queue_url: str,
        entries: list[dict[str, Any]],
    ) -> list[str]:
        """Send up to 10 messages in a batch."""
        response = await self._call(
            queue_name,
            "send_message",
            "send_message_batch",
            QueueUrl=queue_url,
            Entries=entries,
        )
        failed = list(response.get("Failed", []))
        if failed:
            details = ", ".join(
                f"{item.get('Id', '?')}:{item.get('Code', 'Unknown')}"
                for item in failed
            )
            raise QueueBatchError(f"send_message_batch failed for entries: {details}")

        successful = list(response.get("Successful", []))
        ids_by_entry = {
            str(item["Id"]): str(item["MessageId"])
            for item in successful
            if "Id" in item and "MessageId" in item
        }
        missing_entry_ids = [
            str(entry["Id"])
            for entry in entries
            if str(entry["Id"]) not in ids_by_entry
        ]
        if missing_entry_ids:
            raise QueueBatchError(
                "send_message_batch response missing success IDs for entries: "
                + ", ".join(missing_entry_ids)
            )
        message_ids = [ids_by_entry[str(entry["Id"])] for entry in entries]
        return message_ids

    async def receive_messages(
        self,
        queue_name: str,
        queue_url: str,
        *,
        max_messages: int,
        wait_seconds: int,
        visibility_timeout: int | None,
    ) -> list[dict[str, Any]]:
        """Receive up to ``max_messages`` from an SQS queue."""
        kwargs: dict[str, Any] = {
            "QueueUrl": queue_url,
            "MaxNumberOfMessages": max_messages,
            "WaitTimeSeconds": wait_seconds,
            "AttributeNames": ["All"],
            "MessageAttributeNames": ["All"],
        }
        if visibility_timeout is not None:
            kwargs["VisibilityTimeout"] = visibility_timeout

        response = await self._call(
            queue_name,
            "receive_message",
            "receive_message",
            **kwargs,
        )
        return list(response.get("Messages", []))

    async def delete_message(
        self, queue_name: str, queue_url: str, receipt_handle: str
    ) -> None:
        """Delete a single message."""
        await self._call(
            queue_name,
            "delete_message",
            "delete_message",
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle,
        )

    async def change_message_visibility(
        self,
        queue_name: str,
        queue_url: str,
        receipt_handle: str,
        timeout_seconds: int,
    ) -> None:
        """Change a message visibility timeout."""
        await self._call(
            queue_name,
            "change_visibility",
            "change_message_visibility",
            QueueUrl=queue_url,
            ReceiptHandle=receipt_handle,
            VisibilityTimeout=timeout_seconds,
        )

    async def queue_arn(self, queue_name: str, queue_url: str) -> str:
        """Return a queue ARN."""
        attributes = await self.get_queue_attributes(
            queue_name, queue_url, ["QueueArn"]
        )
        queue_arn = attributes.get("QueueArn")
        if not isinstance(queue_arn, str) or not queue_arn.strip():
            raise QueueError(
                f"queue_arn for queue '{queue_name}' returned invalid response: "
                "missing non-empty 'QueueArn' attribute."
            )
        return queue_arn

    async def require_queue_url(self, queue_name: str) -> str:
        """Return a queue URL or raise if it does not exist."""
        if url := await self.get_queue_url(queue_name):
            return url
        raise QueueNotFoundError(f"Queue '{queue_name}' does not exist.")

    def invalidate_queue_url(self, queue_name: str) -> None:
        """Drop a cached queue URL so it will be resolved again on next use."""
        self._queue_urls.pop(queue_name, None)


def uses_local_credentials(endpoint_url: str | None) -> bool:
    """Return whether an endpoint should default to LocalStack-style test creds."""
    if endpoint_url is None:
        return False
    hostname = urlparse(endpoint_url).hostname
    if hostname is None:
        return False
    normalized = hostname.strip().lower()
    if normalized in {"localhost", "localstack", "host.docker.internal"}:
        return True
    if normalized.endswith(".localhost.localstack.cloud"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def client_error_code(exc: ClientError) -> str | None:
    """Extract a normalized error code from a ClientError payload."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    error = response.get("Error")
    if not isinstance(error, dict):
        return None
    code = error.get("Code")
    if not isinstance(code, str):
        return None
    normalized = code.strip()
    if not normalized:
        return None
    return normalized


def response_non_empty_string(
    response: Mapping[str, Any],
    key: str,
    *,
    queue_name: str,
    operation: str,
) -> str:
    """Extract a required non-empty string field from an AWS response payload."""
    value = response.get(key)
    if not isinstance(value, str) or not value.strip():
        raise QueueError(
            f"{operation} for queue '{queue_name}' returned invalid response: "
            f"missing non-empty '{key}'."
        )
    return value


def response_mapping(
    response: Mapping[str, Any],
    key: str,
    *,
    queue_name: str,
    operation: str,
) -> Mapping[str, Any]:
    """Extract a required mapping field from an AWS response payload."""
    value = response.get(key)
    if not isinstance(value, Mapping):
        raise QueueError(
            f"{operation} for queue '{queue_name}' returned invalid response: "
            f"missing mapping '{key}'."
        )
    return value
