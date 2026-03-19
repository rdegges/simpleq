"""Tests for the SimpleQ application class."""

from __future__ import annotations

from simpleq import SimpleQ
from simpleq.config import Config


class TestSimpleQInit:
    def test_default_config(self, mock_sqs):
        sq = SimpleQ()
        assert sq.config.region == "us-east-1"
        assert sq.config.dead_letter_queue is False
        assert sq.config.auto_create is True
        assert sq.config.visibility_timeout == 30

    def test_custom_config(self, mock_sqs):
        sq = SimpleQ(
            region="eu-west-1",
            dead_letter_queue=True,
            visibility_timeout=600,
            auto_create=False,
        )
        assert sq.config.region == "eu-west-1"
        assert sq.config.dead_letter_queue is True
        assert sq.config.visibility_timeout == 600
        assert sq.config.auto_create is False

    def test_endpoint_url(self, mock_sqs):
        sq = SimpleQ(endpoint_url="http://localhost:4566")
        assert sq.config.endpoint_url == "http://localhost:4566"


class TestSimpleQQueues:
    def test_queue_caching(self, sq):
        """Same name returns same Queue object."""
        q1 = sq.queue("emails")
        q2 = sq.queue("emails")
        assert q1 is q2

    def test_different_queues(self, sq):
        """Different names return different Queue objects."""
        q1 = sq.queue("emails")
        q2 = sq.queue("images")
        assert q1 is not q2

    def test_default_queue_name(self, sq):
        """Default queue name is 'default'."""
        q = sq.queue()
        assert q.name == "default"

    def test_queues_property(self, sq):
        """queues property returns all known queues."""
        sq.queue("a")
        sq.queue("b")
        assert set(sq.queues.keys()) == {"a", "b"}


class TestSimpleQTaskRegistry:
    def test_tasks_property(self, sq):
        """tasks property returns all registered tasks."""

        @sq.task
        def task_a():
            pass

        @sq.task(queue="other")
        def task_b():
            pass

        assert len(sq.tasks) == 2

    def test_tasks_is_copy(self, sq):
        """tasks property returns a copy, not the internal dict."""

        @sq.task
        def my_task():
            pass

        tasks = sq.tasks
        tasks.clear()

        # Internal state should be unaffected
        assert len(sq.tasks) == 1


class TestSimpleQCostTracker:
    def test_shared_cost_tracker(self, sq):
        """All queues from the same app share a cost tracker."""
        q1 = sq.queue("a")
        q2 = sq.queue("b")
        assert q1.cost_tracker is q2.cost_tracker
        assert q1.cost_tracker is sq.cost_tracker
