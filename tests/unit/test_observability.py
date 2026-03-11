"""Unit tests for metrics, logging, and cost tracking."""

from __future__ import annotations

from simpleq.observability import CostTracker, PrometheusMetrics, Timer, level_to_int


def test_cost_tracker_aggregates_requests_and_cost() -> None:
    tracker = CostTracker(price_per_million=0.50)
    tracker.track_request("emails", "send_message", count=2)
    tracker.track_request("emails", "receive_message")
    tracker.job_enqueued("emails", count=2)
    tracker.job_completed("emails", duration_ms=25)
    tracker.job_failed("emails")
    tracker.job_decode_failed("emails")
    tracker.job_retried("emails")
    metrics = tracker.metrics_for("emails")
    assert metrics.total_requests == 3
    assert metrics.send_requests == 2
    assert metrics.receive_requests == 1
    assert metrics.jobs_enqueued == 2
    assert metrics.jobs_decode_failed == 1
    assert tracker.total_cost() == 3 * (0.50 / 1_000_000)
    assert metrics.average_processing_time_ms == 25
    assert tracker.snapshot()["emails"]["jobs_processed"] == 1


def test_prometheus_metrics_render() -> None:
    metrics = PrometheusMetrics()
    metrics.record_enqueue("emails")
    metrics.record_processed("emails", status="success", duration_seconds=0.5)
    metrics.record_retry_delay("emails", strategy="exponential", delay_seconds=4)
    metrics.record_queue_depth("emails", 3)
    payload = metrics.render().decode("utf-8")
    assert "simpleq_jobs_enqueued_total" in payload
    assert "simpleq_retry_delay_seconds" in payload
    assert "simpleq_queue_depth" in payload


def test_level_to_int_and_timer() -> None:
    timer = Timer()
    timer.start()
    assert timer.stop() >= 0
    assert level_to_int("INFO") == 20
    assert level_to_int("DEBUG") == 10


def test_average_processing_time_zero() -> None:
    tracker = CostTracker()
    assert tracker.metrics_for("empty").average_processing_time_ms == 0.0
