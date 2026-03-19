"""Tests for Task decorator, .delay(), and .apply()."""

from __future__ import annotations

import pytest

from simpleq import SimpleQ


class TestTaskDecorator:
    def test_bare_decorator(self, sq):
        """@sq.task with no arguments registers the task."""

        @sq.task
        def my_task():
            return 42

        assert "tests.test_task.TestTaskDecorator.test_bare_decorator.<locals>.my_task" in sq.tasks
        assert my_task() == 42

    def test_decorator_with_options(self, sq):
        """@sq.task(queue="emails") registers with the correct queue."""

        @sq.task(queue="emails", retries=3, backoff="linear")
        def send_email(to):
            pass

        task = sq.tasks[send_email.name]
        assert task.queue_name == "emails"
        assert task.retries == 3
        assert task.backoff == "linear"

    def test_fifo_auto_appends_suffix(self, sq):
        """fifo=True auto-appends .fifo to queue name."""

        @sq.task(queue="orders", fifo=True)
        def process_order():
            pass

        assert process_order.queue_name == "orders.fifo"

    def test_fifo_preserves_existing_suffix(self, sq):
        """fifo=True doesn't double-append .fifo."""

        @sq.task(queue="orders.fifo", fifo=True)
        def process_order():
            pass

        assert process_order.queue_name == "orders.fifo"

    def test_async_flag(self, sq):
        """async_=True is stored on the task."""

        @sq.task(async_=True)
        async def fetch_data():
            pass

        assert fetch_data.async_ is True

    def test_task_preserves_function_name(self, sq):
        """Task preserves the original function's __name__."""

        @sq.task
        def my_cool_task():
            pass

        assert my_cool_task.__name__ == "my_cool_task"

    def test_multiple_tasks_registered(self, sq):
        """Multiple tasks are all registered."""

        @sq.task
        def task_a():
            pass

        @sq.task
        def task_b():
            pass

        assert len(sq.tasks) == 2


class TestTaskApply:
    def test_apply_runs_locally(self, sq):
        """.apply() runs the function without touching SQS."""
        results = []

        @sq.task
        def collect(x):
            results.append(x)
            return x * 2

        result = collect.apply(5)
        assert result == 10
        assert results == [5]

    def test_apply_with_kwargs(self, sq):
        """.apply() passes kwargs correctly."""

        @sq.task
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        assert greet.apply("World", greeting="Hi") == "Hi, World!"


class TestTaskDelay:
    def test_delay_sends_to_sqs(self, sq):
        """.delay() sends a job to the correct SQS queue."""

        @sq.task(queue="emails")
        def send_email(to):
            pass

        send_email.delay("user@example.com")

        queue = sq.queue("emails")
        assert queue.num_jobs() == 1

    def test_delay_preserves_args(self, sq):
        """.delay() serializes args correctly into SQS."""

        @sq.task
        def add(a, b):
            return a + b

        add.delay(3, 7)

        queue = sq.queue("default")
        jobs = queue.receive_jobs(max_messages=1)
        assert len(jobs) == 1
        assert jobs[0].task_name == add.name
        assert jobs[0].args == (3, 7)

    def test_delay_with_delay_seconds(self, sq):
        """.delay() accepts _delay_seconds."""

        @sq.task
        def deferred():
            pass

        # Should not raise
        deferred.delay(_delay_seconds=300)

    def test_delay_fifo_with_message_group_id_callable(self, sq):
        """FIFO tasks resolve message_group_id from a callable."""

        @sq.task(
            queue="orders",
            fifo=True,
            message_group_id=lambda order_id: f"group-{order_id}",
        )
        def process_order(order_id):
            pass

        process_order.delay("123")

        queue = sq.queue("orders.fifo")
        jobs = queue.receive_jobs(max_messages=1)
        assert len(jobs) == 1

    def test_delay_fifo_with_message_group_id_string(self, sq):
        """FIFO tasks accept a static string for message_group_id."""

        @sq.task(
            queue="events",
            fifo=True,
            message_group_id="all-events",
        )
        def log_event(event):
            pass

        log_event.delay("click")

        queue = sq.queue("events.fifo")
        assert queue.num_jobs() == 1
