"""Unit tests for the SQS transport wrapper."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from simpleq.config import SimpleQConfig
from simpleq.exceptions import QueueBatchError, QueueNotFoundError
from simpleq.observability import CostTracker, OperationName
from simpleq.sqs import SQSClient, uses_local_credentials


class SpyCostTracker(CostTracker):
    """Capture transport operations for assertions."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, str, int]] = []

    def track_request(
        self, queue_name: str, operation: OperationName, *, count: int = 1
    ) -> None:
        self.calls.append((queue_name, operation, count))


class FakeBotoSQSClient:
    """Simple synchronous boto3 client stub."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tags_by_url: dict[str, dict[str, str]] = {}
        self.batch_successful: list[dict[str, str]] = [
            {"Id": "1", "MessageId": "batch-1"},
            {"Id": "2", "MessageId": "batch-2"},
        ]
        self.batch_failed: list[dict[str, str]] = []
        self.list_queue_pages: dict[str, dict[str, Any]] = {
            "paged:first": {
                "QueueUrls": ["https://example.com/paged-1"],
                "NextToken": "token-1",
            },
            "paged:token-1": {"QueueUrls": ["https://example.com/paged-2"]},
            "loop:first": {
                "QueueUrls": ["https://example.com/loop-1"],
                "NextToken": "loop-token",
            },
            "loop:loop-token": {
                "QueueUrls": ["https://example.com/loop-2"],
                "NextToken": "loop-token",
            },
        }

    def get_queue_url(self, *, QueueName: str) -> dict[str, str]:
        self.calls.append(("get_queue_url", {"QueueName": QueueName}))
        if QueueName == "missing":
            raise ClientError({"Error": {"Code": "QueueDoesNotExist"}}, "GetQueueUrl")
        if QueueName == "broken":
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetQueueUrl")
        return {"QueueUrl": f"https://example.com/{QueueName}"}

    def create_queue(
        self, *, QueueName: str, Attributes: dict[str, str], tags: dict[str, str]
    ) -> dict[str, str]:
        queue_url = f"https://example.com/{QueueName}"
        self.calls.append(
            (
                "create_queue",
                {"QueueName": QueueName, "Attributes": Attributes, "tags": tags},
            )
        )
        self.tags_by_url[queue_url] = dict(tags)
        return {"QueueUrl": queue_url}

    def set_queue_attributes(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("set_queue_attributes", kwargs))
        return {}

    def get_queue_attributes(
        self, *, QueueUrl: str, AttributeNames: list[str]
    ) -> dict[str, dict[str, str]]:
        self.calls.append(
            (
                "get_queue_attributes",
                {"QueueUrl": QueueUrl, "AttributeNames": AttributeNames},
            )
        )
        return {
            "Attributes": {
                "QueueArn": "arn:aws:sqs:us-east-1:123:test",
                "ApproximateNumberOfMessages": "3",
            }
        }

    def list_queues(
        self,
        *,
        QueueNamePrefix: str,
        MaxResults: int | None = None,
        NextToken: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "list_queues",
                {
                    "QueueNamePrefix": QueueNamePrefix,
                    "MaxResults": MaxResults,
                    "NextToken": NextToken,
                },
            )
        )
        if QueueNamePrefix == "empty":
            return {}
        if QueueNamePrefix in {"paged", "loop"}:
            page_key = f"{QueueNamePrefix}:{NextToken or 'first'}"
            return dict(self.list_queue_pages.get(page_key, {}))
        return {"QueueUrls": ["https://example.com/emails"]}

    def list_queue_tags(self, *, QueueUrl: str) -> dict[str, dict[str, str]]:
        self.calls.append(("list_queue_tags", {"QueueUrl": QueueUrl}))
        return {"Tags": dict(self.tags_by_url.get(QueueUrl, {}))}

    def tag_queue(self, *, QueueUrl: str, Tags: dict[str, str]) -> dict[str, Any]:
        self.calls.append(("tag_queue", {"QueueUrl": QueueUrl, "Tags": Tags}))
        queue_tags = self.tags_by_url.setdefault(QueueUrl, {})
        queue_tags.update(Tags)
        return {}

    def untag_queue(self, *, QueueUrl: str, TagKeys: list[str]) -> dict[str, Any]:
        self.calls.append(("untag_queue", {"QueueUrl": QueueUrl, "TagKeys": TagKeys}))
        queue_tags = self.tags_by_url.setdefault(QueueUrl, {})
        for key in TagKeys:
            queue_tags.pop(key, None)
        return {}

    def delete_queue(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete_queue", kwargs))
        return {}

    def purge_queue(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("purge_queue", kwargs))
        return {}

    def send_message(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(("send_message", kwargs))
        return {"MessageId": "mid-1"}

    def send_message_batch(self, **kwargs: Any) -> dict[str, list[dict[str, str]]]:
        self.calls.append(("send_message_batch", kwargs))
        return {
            "Successful": self.batch_successful,
            "Failed": self.batch_failed,
        }

    def receive_message(self, **kwargs: Any) -> dict[str, list[dict[str, str]]]:
        self.calls.append(("receive_message", kwargs))
        return {"Messages": [{"Body": "{}", "MessageId": "1"}]}

    def delete_message(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete_message", kwargs))
        return {}

    def change_message_visibility(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("change_message_visibility", kwargs))
        return {}


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> SQSClient:
    fake = FakeBotoSQSClient()
    monkeypatch.setattr("simpleq.sqs.boto3.client", lambda *args, **kwargs: fake)
    client = SQSClient(
        SimpleQConfig.from_overrides(endpoint_url="http://localhost:4566"),
        CostTracker(),
    )
    client._client = fake
    return client


@pytest.mark.asyncio
async def test_get_queue_url_cache_and_errors(transport: SQSClient) -> None:
    assert await transport.get_queue_url("emails") == "https://example.com/emails"
    assert await transport.get_queue_url("emails") == "https://example.com/emails"
    assert await transport.get_queue_url("missing") is None
    with pytest.raises(ClientError):
        await transport.get_queue_url("broken")


@pytest.mark.asyncio
async def test_get_queue_url_tracks_get_queue_url_operation() -> None:
    fake = FakeBotoSQSClient()
    tracker = SpyCostTracker()
    transport = SQSClient(
        SimpleQConfig.from_overrides(endpoint_url="http://localhost:4566"),
        tracker,
    )
    transport._client = fake

    assert await transport.get_queue_url("emails") == "https://example.com/emails"
    assert tracker.calls == [("emails", "get_queue_url", 1)]


@pytest.mark.asyncio
async def test_transport_happy_path_methods(transport: SQSClient) -> None:
    assert (
        await transport.ensure_queue(
            "jobs", attributes={"A": "1"}, tags={"env": "test"}
        )
        == "https://example.com/jobs"
    )
    await transport.set_queue_attributes(
        "jobs", "https://example.com/jobs", {"VisibilityTimeout": "30"}
    )
    attrs = await transport.get_queue_attributes(
        "jobs", "https://example.com/jobs", ["QueueArn"]
    )
    assert attrs["QueueArn"].startswith("arn:")
    assert await transport.list_queues() == ["https://example.com/emails"]
    assert await transport.list_queues("empty") == []
    assert (
        await transport.send_message(
            "jobs",
            "https://example.com/jobs",
            message_body="{}",
            delay_seconds=5,
            message_group_id="group-1",
            deduplication_id="dedup-1",
            message_attributes={
                "source": {"DataType": "String", "StringValue": "tests"}
            },
        )
        == "mid-1"
    )
    assert await transport.send_message_batch(
        "jobs",
        "https://example.com/jobs",
        [
            {"Id": "1", "MessageBody": "{}"},
            {"Id": "2", "MessageBody": "{}"},
        ],
    ) == ["batch-1", "batch-2"]
    messages = await transport.receive_messages(
        "jobs",
        "https://example.com/jobs",
        max_messages=1,
        wait_seconds=0,
        visibility_timeout=None,
    )
    assert messages[0]["MessageId"] == "1"
    await transport.delete_message("jobs", "https://example.com/jobs", "receipt")
    await transport.change_message_visibility(
        "jobs", "https://example.com/jobs", "receipt", 3
    )
    assert (
        await transport.queue_arn("jobs", "https://example.com/jobs")
        == "arn:aws:sqs:us-east-1:123:test"
    )
    assert await transport.require_queue_url("emails") == "https://example.com/emails"
    await transport.delete_queue("jobs", "https://example.com/jobs")
    await transport.purge_queue("jobs", "https://example.com/jobs")


@pytest.mark.asyncio
async def test_ensure_queue_reconciles_existing_attributes(
    transport: SQSClient,
) -> None:
    url = await transport.ensure_queue(
        "emails",
        attributes={"VisibilityTimeout": "45", "ReceiveMessageWaitTimeSeconds": "5"},
    )

    assert url == "https://example.com/emails"
    assert ("get_queue_url", {"QueueName": "emails"}) in transport.client.calls
    assert (
        "set_queue_attributes",
        {
            "QueueUrl": "https://example.com/emails",
            "Attributes": {
                "VisibilityTimeout": "45",
                "ReceiveMessageWaitTimeSeconds": "5",
            },
        },
    ) in transport.client.calls
    assert not any(call[0] == "create_queue" for call in transport.client.calls)


@pytest.mark.asyncio
async def test_ensure_queue_reconciles_existing_tags(transport: SQSClient) -> None:
    transport.client.tags_by_url["https://example.com/emails"] = {
        "env": "dev",
        "owner": "legacy",
    }

    url = await transport.ensure_queue(
        "emails",
        tags={"env": "prod", "team": "platform"},
    )

    assert url == "https://example.com/emails"
    assert ("list_queue_tags", {"QueueUrl": "https://example.com/emails"}) in (
        transport.client.calls
    )
    assert (
        "tag_queue",
        {
            "QueueUrl": "https://example.com/emails",
            "Tags": {"env": "prod", "team": "platform"},
        },
    ) in transport.client.calls
    assert (
        "untag_queue",
        {
            "QueueUrl": "https://example.com/emails",
            "TagKeys": ["owner"],
        },
    ) in transport.client.calls
    assert transport.client.tags_by_url["https://example.com/emails"] == {
        "env": "prod",
        "team": "platform",
    }


@pytest.mark.asyncio
async def test_ensure_queue_skips_tag_reconciliation_when_tags_unspecified(
    transport: SQSClient,
) -> None:
    await transport.ensure_queue("emails", attributes={"VisibilityTimeout": "45"})

    assert not any(
        call[0] in {"list_queue_tags", "tag_queue", "untag_queue"}
        for call in transport.client.calls
    )


@pytest.mark.asyncio
async def test_require_queue_url_raises(transport: SQSClient) -> None:
    with pytest.raises(QueueNotFoundError):
        await transport.require_queue_url("missing")


@pytest.mark.asyncio
async def test_list_queues_follows_pagination_tokens(transport: SQSClient) -> None:
    queues = await transport.list_queues("paged")

    assert queues == ["https://example.com/paged-1", "https://example.com/paged-2"]
    list_calls = [
        payload
        for call, payload in transport.client.calls
        if call == "list_queues" and payload["QueueNamePrefix"] == "paged"
    ]
    assert list_calls == [
        {"QueueNamePrefix": "paged", "MaxResults": 1000, "NextToken": None},
        {"QueueNamePrefix": "paged", "MaxResults": 1000, "NextToken": "token-1"},
    ]


@pytest.mark.asyncio
async def test_list_queues_stops_on_repeated_next_token(transport: SQSClient) -> None:
    queues = await transport.list_queues("loop")

    assert queues == ["https://example.com/loop-1", "https://example.com/loop-2"]
    list_calls = [
        payload
        for call, payload in transport.client.calls
        if call == "list_queues" and payload["QueueNamePrefix"] == "loop"
    ]
    assert len(list_calls) == 2


@pytest.mark.asyncio
async def test_send_message_batch_preserves_entry_order(transport: SQSClient) -> None:
    transport.client.batch_successful = [
        {"Id": "2", "MessageId": "batch-2"},
        {"Id": "1", "MessageId": "batch-1"},
    ]
    ids = await transport.send_message_batch(
        "jobs",
        "https://example.com/jobs",
        [
            {"Id": "1", "MessageBody": "{}"},
            {"Id": "2", "MessageBody": "{}"},
        ],
    )
    assert ids == ["batch-1", "batch-2"]


@pytest.mark.asyncio
async def test_send_message_batch_raises_on_partial_failure(
    transport: SQSClient,
) -> None:
    transport.client.batch_failed = [
        {"Id": "2", "Code": "InvalidMessageContents", "Message": "bad body"},
    ]
    with pytest.raises(QueueBatchError, match="InvalidMessageContents"):
        await transport.send_message_batch(
            "jobs",
            "https://example.com/jobs",
            [
                {"Id": "1", "MessageBody": "{}"},
                {"Id": "2", "MessageBody": "{bad-json"},
            ],
        )


@pytest.mark.asyncio
async def test_invalidate_queue_url_drops_cached_entry(transport: SQSClient) -> None:
    await transport.get_queue_url("emails")
    assert transport._queue_urls["emails"] == "https://example.com/emails"

    transport.invalidate_queue_url("emails")

    assert "emails" not in transport._queue_urls


def test_uses_local_credentials() -> None:
    assert uses_local_credentials("http://localhost:4566") is True
    assert uses_local_credentials("http://localstack:4566") is True
    assert uses_local_credentials("http://host.docker.internal:4566") is True
    assert uses_local_credentials("http://[::1]:4566") is True
    assert (
        uses_local_credentials(
            "https://sqs.us-east-1.localhost.localstack.cloud:4566"
        )
        is True
    )
    assert (
        uses_local_credentials("https://sqs.us-east-1.amazonaws.com/localstack-proxy")
        is False
    )
    assert uses_local_credentials("https://sqs.us-east-1.amazonaws.com") is False
