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
        "Attributes": {"ApproximateReceiveCount": "2"},
        "MessageAttributes": {
            "source": {"DataType": "String", "StringValue": "tests"},
        },
    }
    restored = Job.from_sqs_message("emails", message)
    assert restored.receipt_handle == "abc"
    assert restored.message_id == "mid"
    assert restored.receive_count == 2
    assert restored.message_attributes == {"source": "tests"}


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
