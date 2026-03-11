"""Unit tests for the Job model."""

from __future__ import annotations

import pytest

from simpleq.job import Job


def test_job_roundtrip_json_message() -> None:
    job = Job(
        task_name="tests.fixtures.tasks:record_async",
        args=("hello",),
        kwargs={},
        queue_name="default",
    )
    restored = Job.from_message_body(job.to_message_body())
    assert restored.task_name == job.task_name
    assert restored.args == ("hello",)
    assert restored.kwargs == {}
    assert restored.queue_name == "default"


def test_job_from_sqs_message_extracts_attributes() -> None:
    message = {
        "Body": Job(
            task_name="tests.fixtures.tasks:record_sync",
            args=("value",),
            kwargs={},
            queue_name="emails",
        ).to_message_body(),
        "ReceiptHandle": "abc",
        "MessageId": "mid",
        "Attributes": {
            "ApproximateReceiveCount": "2",
            "MessageGroupId": "group-1",
            "MessageDeduplicationId": "dedup-1",
        },
        "MessageAttributes": {
            "source": {"DataType": "String", "StringValue": "tests"},
        },
    }
    restored = Job.from_sqs_message("emails", message)
    assert restored.receipt_handle == "abc"
    assert restored.message_id == "mid"
    assert restored.receive_count == 2
    assert restored.message_attributes == {"source": "tests"}
    assert restored.metadata["message_group_id"] == "group-1"
    assert restored.metadata["deduplication_id"] == "dedup-1"


def test_job_from_sqs_message_prefers_current_system_routing_attributes() -> None:
    message = {
        "Body": Job(
            task_name="tests.fixtures.tasks:record_sync",
            args=("value",),
            kwargs={},
            queue_name="emails",
            metadata={
                "message_group_id": "stale-group",
                "deduplication_id": "stale-dedup",
                "_simpleq_message_group_id": "stale-group",
                "_simpleq_deduplication_id": "stale-dedup",
            },
        ).to_message_body(),
        "ReceiptHandle": "abc",
        "MessageId": "mid",
        "Attributes": {
            "ApproximateReceiveCount": "2",
            "MessageGroupId": "group-1",
            "MessageDeduplicationId": "dedup-1",
        },
        "MessageAttributes": {},
    }

    restored = Job.from_sqs_message("emails", message)

    assert restored.metadata["message_group_id"] == "group-1"
    assert restored.metadata["_simpleq_message_group_id"] == "group-1"
    assert restored.metadata["deduplication_id"] == "dedup-1"
    assert restored.metadata["_simpleq_deduplication_id"] == "dedup-1"


def test_job_with_attempt_copies_error_metadata() -> None:
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("value",),
        kwargs={},
        queue_name="emails",
    )
    retried = job.with_attempt(3, error="boom")
    assert retried.attempt == 3
    assert retried.metadata["last_error"] == "boom"
    assert job.metadata == {}


def test_job_from_message_body_rejects_non_mapping_metadata() -> None:
    payload = {
        "version": "2.0",
        "job_id": "abc",
        "task_name": "tests.fixtures.tasks:record_sync",
        "queue_name": "emails",
        "serializer": "json",
        "args": ["hello"],
        "kwargs": {},
        "attempt": 0,
        "enqueued_at": "2026-03-07T00:00:00+00:00",
        "metadata": [],
    }
    import json

    with pytest.raises(TypeError):
        Job.from_message_body(json.dumps(payload))


def test_job_from_sqs_message_tolerates_non_mapping_message_attributes() -> None:
    message = {
        "Body": Job(
            task_name="tests.fixtures.tasks:record_sync",
            args=("value",),
            kwargs={},
            queue_name="emails",
        ).to_message_body(),
        "MessageAttributes": None,
    }

    restored = Job.from_sqs_message("emails", message)

    assert restored.message_attributes == {}


def test_job_from_sqs_message_ignores_malformed_attribute_entries() -> None:
    message = {
        "Body": Job(
            task_name="tests.fixtures.tasks:record_sync",
            args=("value",),
            kwargs={},
            queue_name="emails",
        ).to_message_body(),
        "MessageAttributes": {
            "valid": {"DataType": "String", "StringValue": "x"},
            "non_mapping": "bad-shape",
            "missing_value": {"DataType": "String"},
        },
    }

    restored = Job.from_sqs_message("emails", message)

    assert restored.message_attributes == {"valid": "x"}


def test_job_from_sqs_message_defaults_receive_count_when_attributes_missing() -> None:
    message = {
        "Body": Job(
            task_name="tests.fixtures.tasks:record_sync",
            args=("value",),
            kwargs={},
            queue_name="emails",
        ).to_message_body(),
        "Attributes": None,
    }

    restored = Job.from_sqs_message("emails", message)

    assert restored.receive_count == 1


@pytest.mark.parametrize("raw_count", ["not-a-number", "0", "-2", ""])
def test_job_from_sqs_message_defaults_receive_count_for_invalid_values(
    raw_count: str,
) -> None:
    message = {
        "Body": Job(
            task_name="tests.fixtures.tasks:record_sync",
            args=("value",),
            kwargs={},
            queue_name="emails",
        ).to_message_body(),
        "Attributes": {"ApproximateReceiveCount": raw_count},
    }

    restored = Job.from_sqs_message("emails", message)

    assert restored.receive_count == 1
