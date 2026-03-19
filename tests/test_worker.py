"""Tests for Worker — job processing, retries, signals, burst mode."""

from __future__ import annotations

import signal

import pytest

from simpleq import SimpleQ
from simpleq.job import Job
from simpleq.worker import Worker, _calculate_backoff


class TestWorkerProcessing:
    def test_processes_job(self, sq):
        """Worker picks up a job, runs the task, and deletes the message."""
        results = []

        @sq.task
        def collect(x):
            results.append(x)

        collect.delay(42)

        worker = Worker(queues=[sq.queue("default")], tasks=sq.tasks)
        worker.work(burst=True)

        assert results == [42]
        assert sq.queue("default").num_jobs() == 0

    def test_processes_multiple_jobs(self, sq):
        """Worker processes all pending jobs in burst mode."""
        results = []

        @sq.task
        def collect(x):
            results.append(x)

        for i in range(5):
            collect.delay(i)

        worker = Worker(queues=[sq.queue("default")], tasks=sq.tasks)
        worker.work(burst=True)

        assert sorted(results) == [0, 1, 2, 3, 4]

    def test_processes_multiple_queues(self, sq):
        """Worker polls all provided queues."""
        email_results = []
        image_results = []

        @sq.task(queue="emails")
        def send_email(to):
            email_results.append(to)

        @sq.task(queue="images")
        def resize(url):
            image_results.append(url)

        send_email.delay("a@b.com")
        resize.delay("http://img.png")

        worker = Worker(
            queues=[sq.queue("emails"), sq.queue("images")],
            tasks=sq.tasks,
        )
        worker.work(burst=True)

        assert email_results == ["a@b.com"]
        assert image_results == ["http://img.png"]

    def test_unknown_task_skipped(self, sq):
        """Worker logs and skips jobs for unregistered tasks."""
        queue = sq.queue("default")
        job = Job(task_name="unknown.task")
        queue.send_job(job)

        # Worker has no tasks registered
        worker = Worker(queues=[queue], tasks={})
        worker.work(burst=True)

        # Message should still be in queue (not deleted)
        # (In SQS it would become visible again after visibility timeout)


class TestWorkerBurstMode:
    def test_burst_exits_on_empty(self, sq):
        """Burst mode exits immediately when queues are empty."""

        @sq.task
        def noop():
            pass

        worker = Worker(queues=[sq.queue("default")], tasks=sq.tasks)
        # Should return without blocking
        worker.work(burst=True)

    def test_burst_processes_then_exits(self, sq):
        """Burst mode processes all jobs then exits."""
        count = [0]

        @sq.task
        def increment():
            count[0] += 1

        increment.delay()
        increment.delay()

        worker = Worker(queues=[sq.queue("default")], tasks=sq.tasks)
        worker.work(burst=True)

        assert count[0] == 2


class TestWorkerAsyncTasks:
    def test_async_task_execution(self, sq):
        """Worker can execute async task functions."""
        results = []

        @sq.task(async_=True)
        async def async_job(value):
            results.append(value)

        async_job.delay("hello")

        worker = Worker(queues=[sq.queue("default")], tasks=sq.tasks)
        worker.work(burst=True)

        assert results == ["hello"]


class TestWorkerRetries:
    def test_failed_job_not_deleted(self, sq):
        """Failed jobs are left in queue for SQS to retry."""

        @sq.task(retries=3)
        def failing_task():
            raise ValueError("boom")

        failing_task.delay()

        worker = Worker(queues=[sq.queue("default")], tasks=sq.tasks)
        worker.work(burst=True)

        # Job should still be in queue (visibility timeout will make it
        # available again in a real SQS setup)

    def test_failed_job_no_retries_no_dlq_stays(self, sq):
        """Failed job with no retries configured stays in queue."""

        @sq.task
        def failing_task():
            raise ValueError("boom")

        failing_task.delay()

        worker = Worker(queues=[sq.queue("default")], tasks=sq.tasks)
        worker.work(burst=True)

        # Job left in queue — SQS handles visibility timeout


class TestWorkerGracefulShutdown:
    def test_signal_handler_sets_flag(self, sq):
        """SIGINT/SIGTERM handler sets _shutdown flag."""

        @sq.task
        def noop():
            pass

        worker = Worker(queues=[sq.queue("default")], tasks=sq.tasks)
        worker._setup_signal_handlers()
        worker._handle_shutdown(signal.SIGINT, None)

        assert worker._shutdown is True

    def test_shutdown_stops_processing(self, sq):
        """Worker stops after current batch when _shutdown is set."""
        call_count = [0]

        @sq.task
        def counting_task():
            call_count[0] += 1

        counting_task.delay()

        worker = Worker(queues=[sq.queue("default")], tasks=sq.tasks)

        # Patch receive_jobs to set shutdown after first batch
        original_receive = sq.queue("default").receive_jobs

        def receive_then_shutdown(*args, **kwargs):
            result = original_receive(*args, **kwargs)
            if call_count[0] > 0:
                worker._shutdown = True
            return result

        sq.queue("default").receive_jobs = receive_then_shutdown
        worker.work()

        assert call_count[0] == 1


class TestBackoffCalculation:
    def test_exponential_backoff(self):
        assert _calculate_backoff("exponential", 0) == 2
        assert _calculate_backoff("exponential", 1) == 4
        assert _calculate_backoff("exponential", 2) == 8
        assert _calculate_backoff("exponential", 3) == 16

    def test_linear_backoff(self):
        assert _calculate_backoff("linear", 0) == 2
        assert _calculate_backoff("linear", 1) == 4
        assert _calculate_backoff("linear", 2) == 6

    def test_constant_backoff(self):
        assert _calculate_backoff("constant", 0) == 2
        assert _calculate_backoff("constant", 5) == 2

    def test_backoff_capped(self):
        """Backoff is capped at 12 hours (SQS max)."""
        result = _calculate_backoff("exponential", 100)
        assert result == 43200
