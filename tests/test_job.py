"""Tests for Job serialization and deserialization."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from simpleq.exceptions import MessageTooLargeError, SerializationError
from simpleq.job import Job


class TestJobSerialization:
    def test_round_trip(self):
        """Job serializes and deserializes back to equivalent data."""
        job = Job(
            task_name="myapp.tasks.send_email",
            args=("user@example.com",),
            kwargs={"subject": "Hello"},
        )
        serialized = job.serialize()
        restored = Job.deserialize(serialized)

        assert restored.task_name == job.task_name
        assert restored.args == job.args
        assert restored.kwargs == job.kwargs

    def test_empty_args(self):
        """Job with no args serializes correctly."""
        job = Job(task_name="myapp.tasks.noop")
        serialized = job.serialize()
        restored = Job.deserialize(serialized)

        assert restored.task_name == "myapp.tasks.noop"
        assert restored.args == ()
        assert restored.kwargs == {}

    def test_complex_args(self):
        """Pickle handles complex Python objects."""
        data = {"nested": [1, 2, {"key": (3, 4)}], "set_val": {5, 6}}
        job = Job(
            task_name="test",
            args=(data,),
            kwargs={"flag": True, "count": 42},
        )
        serialized = job.serialize()
        restored = Job.deserialize(serialized)

        assert restored.args[0] == data
        assert restored.kwargs == {"flag": True, "count": 42}

    def test_preserves_created_at(self):
        """Timestamp survives serialization."""
        ts = datetime(2026, 3, 18, 12, 0, 0, tzinfo=timezone.utc)
        job = Job(task_name="test", created_at=ts)
        serialized = job.serialize()
        restored = Job.deserialize(serialized)

        assert restored.created_at == ts

    def test_deserialize_with_receipt_handle(self):
        """Receipt handle is passed through on deserialize."""
        job = Job(task_name="test")
        serialized = job.serialize()
        restored = Job.deserialize(
            serialized, receipt_handle="abc-123", message_id="msg-456"
        )

        assert restored.receipt_handle == "abc-123"
        assert restored.id == "msg-456"

    def test_deserialize_with_receive_count(self):
        """Receive count is passed through on deserialize."""
        job = Job(task_name="test")
        serialized = job.serialize()
        restored = Job.deserialize(serialized, receive_count=3)

        assert restored.receive_count == 3


class TestJobErrors:
    def test_unpicklable_args_raises_serialization_error(self):
        """Non-picklable arguments produce a clear error."""
        import threading

        lock = threading.Lock()
        job = Job(task_name="test", args=(lock,))

        with pytest.raises(SerializationError, match="picklable"):
            job.serialize()

    def test_oversized_payload_raises_message_too_large(self):
        """Payload over 256KB produces a clear error."""
        big_data = "x" * 300_000
        job = Job(task_name="test", args=(big_data,))

        with pytest.raises(MessageTooLargeError, match="256KB"):
            job.serialize()

    def test_corrupt_body_raises_serialization_error(self):
        """Corrupt message body produces a clear error."""
        with pytest.raises(SerializationError, match="deserialize"):
            Job.deserialize("not-valid-base64-pickle")
