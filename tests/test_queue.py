"""Tests for Queue — SQS operations via moto."""

from __future__ import annotations

import pytest

from simpleq.config import Config
from simpleq.cost import CostTracker
from simpleq.exceptions import QueueError, QueueNotFoundError
from simpleq.job import Job
from simpleq.queue import Queue


class TestQueueCreation:
    def test_auto_creates_queue(self, mock_sqs, sqs_client):
        """Queue is auto-created on first access when auto_create=True."""
        config = Config()
        q = Queue(name="my-queue", config=config, cost_tracker=CostTracker())

        # Accessing .url triggers auto-creation
        url = q.url
        assert "my-queue" in url

        # Verify it exists in SQS
        response = sqs_client.get_queue_url(QueueName="my-queue")
        assert response["QueueUrl"] == url

    def test_auto_create_false_raises(self, mock_sqs):
        """auto_create=False raises QueueNotFoundError for missing queues."""
        config = Config(auto_create=False)
        q = Queue(name="nonexistent", config=config, cost_tracker=CostTracker())

        with pytest.raises(QueueNotFoundError, match="does not exist"):
            _ = q.url

    def test_uses_existing_queue(self, mock_sqs, sqs_client):
        """Queue uses an existing SQS queue if it exists."""
        sqs_client.create_queue(QueueName="existing")
        config = Config()
        q = Queue(name="existing", config=config, cost_tracker=CostTracker())

        url = q.url
        assert "existing" in url

    def test_fifo_queue_detection(self, mock_sqs):
        """Queue.fifo is True when name ends with .fifo."""
        config = Config()
        q = Queue(name="orders.fifo", config=config, cost_tracker=CostTracker())
        assert q.fifo is True

        q2 = Queue(name="emails", config=config, cost_tracker=CostTracker())
        assert q2.fifo is False

    def test_fifo_queue_creation(self, mock_sqs, sqs_client):
        """FIFO queues are created with proper attributes."""
        config = Config()
        q = Queue(name="orders.fifo", config=config, cost_tracker=CostTracker())
        _ = q.url

        attrs = sqs_client.get_queue_attributes(
            QueueUrl=q.url, AttributeNames=["FifoQueue"]
        )
        assert attrs["Attributes"]["FifoQueue"] == "true"

    def test_custom_visibility_timeout(self, mock_sqs, sqs_client):
        """Custom visibility timeout is set on queue creation."""
        config = Config(visibility_timeout=300)
        q = Queue(name="custom-vt", config=config, cost_tracker=CostTracker())
        _ = q.url

        attrs = sqs_client.get_queue_attributes(
            QueueUrl=q.url, AttributeNames=["VisibilityTimeout"]
        )
        assert attrs["Attributes"]["VisibilityTimeout"] == "300"

    def test_repr(self, mock_sqs):
        config = Config()
        q = Queue(name="emails", config=config, cost_tracker=CostTracker())
        assert 'name="emails"' in repr(q)
        assert 'region="us-east-1"' in repr(q)


class TestQueueSendReceive:
    def test_send_and_receive_job(self, mock_sqs):
        """Job round-trips through SQS."""
        config = Config()
        q = Queue(name="test", config=config, cost_tracker=CostTracker())

        job = Job(task_name="send_email", args=("a@b.com",), kwargs={"x": 1})
        q.send_job(job)

        received = q.receive_jobs(max_messages=1)
        assert len(received) == 1
        assert received[0].task_name == "send_email"
        assert received[0].args == ("a@b.com",)
        assert received[0].kwargs == {"x": 1}
        assert received[0].receipt_handle is not None

    def test_send_with_delay(self, mock_sqs):
        """Delayed jobs are accepted by SQS."""
        config = Config()
        q = Queue(name="test", config=config, cost_tracker=CostTracker())
        job = Job(task_name="test")

        # Should not raise — SQS accepts delay_seconds
        q.send_job(job, delay_seconds=60)

    def test_send_fifo_with_group_id(self, mock_sqs):
        """FIFO queue accepts message_group_id."""
        config = Config()
        q = Queue(name="orders.fifo", config=config, cost_tracker=CostTracker())
        job = Job(task_name="process_order", args=("order-1",))

        q.send_job(job, message_group_id="customer-123")

        received = q.receive_jobs(max_messages=1)
        assert len(received) == 1
        assert received[0].task_name == "process_order"

    def test_delete_job(self, mock_sqs):
        """Deleted jobs are removed from the queue."""
        config = Config()
        q = Queue(name="test", config=config, cost_tracker=CostTracker())
        job = Job(task_name="test")
        q.send_job(job)

        received = q.receive_jobs(max_messages=1)
        assert len(received) == 1

        q.delete_job(received[0])

        # Queue should be empty now
        assert q.num_jobs() == 0

    def test_delete_job_without_receipt_handle_raises(self, mock_sqs):
        """Deleting a job with no receipt handle raises QueueError."""
        config = Config()
        q = Queue(name="test", config=config, cost_tracker=CostTracker())
        job = Job(task_name="test")

        with pytest.raises(QueueError, match="receipt handle"):
            q.delete_job(job)

    def test_num_jobs(self, mock_sqs):
        """num_jobs returns approximate message count."""
        config = Config()
        q = Queue(name="test", config=config, cost_tracker=CostTracker())

        assert q.num_jobs() == 0

        q.send_job(Job(task_name="a"))
        q.send_job(Job(task_name="b"))

        assert q.num_jobs() == 2


class TestQueueOperations:
    def test_purge(self, mock_sqs):
        """Purge removes all messages."""
        config = Config()
        q = Queue(name="test", config=config, cost_tracker=CostTracker())

        q.send_job(Job(task_name="a"))
        q.send_job(Job(task_name="b"))
        assert q.num_jobs() == 2

        q.purge()
        assert q.num_jobs() == 0

    def test_delete_queue(self, mock_sqs, sqs_client):
        """Delete removes the queue from SQS."""
        config = Config()
        q = Queue(name="to-delete", config=config, cost_tracker=CostTracker())
        _ = q.url  # ensure created

        q.delete()

        with pytest.raises(Exception):
            sqs_client.get_queue_url(QueueName="to-delete")


class TestQueueDLQ:
    def test_dlq_created_with_flag(self, mock_sqs, sqs_client):
        """DLQ is created alongside the main queue when enabled."""
        config = Config(dead_letter_queue=True)
        q = Queue(name="emails", config=config, cost_tracker=CostTracker())
        _ = q.url

        # DLQ should exist
        dlq_resp = sqs_client.get_queue_url(QueueName="emails-dlq")
        assert "emails-dlq" in dlq_resp["QueueUrl"]

    def test_dlq_not_created_without_flag(self, mock_sqs, sqs_client):
        """DLQ is not created when dead_letter_queue=False."""
        config = Config(dead_letter_queue=False)
        q = Queue(name="emails", config=config, cost_tracker=CostTracker())
        _ = q.url

        with pytest.raises(Exception):
            sqs_client.get_queue_url(QueueName="emails-dlq")

    def test_get_dlq_jobs_no_dlq_raises(self, mock_sqs):
        """Reading DLQ when none exists raises QueueNotFoundError."""
        config = Config()
        q = Queue(name="no-dlq", config=config, cost_tracker=CostTracker())
        _ = q.url

        with pytest.raises(QueueNotFoundError, match="No DLQ configured"):
            q.get_dlq_jobs()

    def test_fifo_dlq_naming(self, mock_sqs, sqs_client):
        """FIFO DLQ uses correct naming: name-dlq.fifo."""
        config = Config(dead_letter_queue=True)
        q = Queue(name="orders.fifo", config=config, cost_tracker=CostTracker())
        _ = q.url

        dlq_resp = sqs_client.get_queue_url(QueueName="orders-dlq.fifo")
        assert "orders-dlq.fifo" in dlq_resp["QueueUrl"]


class TestQueueCostTracking:
    def test_send_tracks_cost(self, mock_sqs):
        """Sending a job increments the send counter."""
        tracker = CostTracker()
        config = Config()
        q = Queue(name="test", config=config, cost_tracker=tracker)

        q.send_job(Job(task_name="test"))

        cost = tracker.get_queue_cost("test")
        assert cost.send_requests == 1

    def test_receive_tracks_cost(self, mock_sqs):
        """Receiving jobs increments the receive counter."""
        tracker = CostTracker()
        config = Config()
        q = Queue(name="test", config=config, cost_tracker=tracker)
        _ = q.url  # trigger queue creation

        q.receive_jobs()

        cost = tracker.get_queue_cost("test")
        assert cost.receive_requests == 1

    def test_delete_tracks_cost(self, mock_sqs):
        """Deleting a job increments the delete counter."""
        tracker = CostTracker()
        config = Config()
        q = Queue(name="test", config=config, cost_tracker=tracker)

        q.send_job(Job(task_name="test"))
        jobs = q.receive_jobs(max_messages=1)
        q.delete_job(jobs[0])

        cost = tracker.get_queue_cost("test")
        assert cost.delete_requests == 1
