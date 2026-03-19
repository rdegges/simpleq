"""Tests for CostTracker."""

from __future__ import annotations

from simpleq.cost import CostTracker, SQS_PRICE_PER_REQUEST


class TestCostTracker:
    def test_track_send(self):
        tracker = CostTracker()
        tracker.track_send("emails")
        tracker.track_send("emails")

        cost = tracker.get_queue_cost("emails")
        assert cost.send_requests == 2

    def test_track_receive(self):
        tracker = CostTracker()
        tracker.track_receive("emails", count=5)

        cost = tracker.get_queue_cost("emails")
        assert cost.receive_requests == 5

    def test_track_delete(self):
        tracker = CostTracker()
        tracker.track_delete("emails")

        cost = tracker.get_queue_cost("emails")
        assert cost.delete_requests == 1

    def test_track_other(self):
        tracker = CostTracker()
        tracker.track_other("emails", count=3)

        cost = tracker.get_queue_cost("emails")
        assert cost.other_requests == 3

    def test_total_requests(self):
        tracker = CostTracker()
        tracker.track_send("emails", 10)
        tracker.track_receive("emails", 20)
        tracker.track_delete("emails", 10)
        tracker.track_other("emails", 5)

        cost = tracker.get_queue_cost("emails")
        assert cost.total_requests == 45

    def test_estimated_cost(self):
        tracker = CostTracker()
        tracker.track_send("emails", 1_000_000)

        cost = tracker.get_queue_cost("emails")
        assert abs(cost.estimated_cost - 0.40) < 0.001

    def test_total_cost_across_queues(self):
        tracker = CostTracker()
        tracker.track_send("emails", 500_000)
        tracker.track_send("images", 500_000)

        assert abs(tracker.total_cost - 0.40) < 0.001

    def test_get_all(self):
        tracker = CostTracker()
        tracker.track_send("a")
        tracker.track_send("b")

        all_costs = tracker.get_all()
        assert set(all_costs.keys()) == {"a", "b"}

    def test_reset(self):
        tracker = CostTracker()
        tracker.track_send("emails")
        tracker.reset()

        assert tracker.get_all() == {}
        assert tracker.total_cost == 0.0

    def test_new_queue_starts_at_zero(self):
        tracker = CostTracker()
        cost = tracker.get_queue_cost("new-queue")
        assert cost.total_requests == 0
        assert cost.estimated_cost == 0.0
