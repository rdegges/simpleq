"""Tests for the SimpleQ CLI."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from simpleq.cli import app

runner = CliRunner()


class TestCLIQueueCommands:
    def test_queue_list_empty(self, mock_sqs):
        result = runner.invoke(app, ["queue", "list"])
        assert result.exit_code == 0
        assert "No queues" in result.output

    def test_queue_create(self, mock_sqs):
        result = runner.invoke(app, ["queue", "create", "my-queue"])
        assert result.exit_code == 0
        assert "created" in result.output

    def test_queue_create_fifo(self, mock_sqs):
        result = runner.invoke(app, ["queue", "create", "orders", "--fifo"])
        assert result.exit_code == 0
        assert "orders.fifo" in result.output

    def test_queue_list_after_create(self, mock_sqs):
        runner.invoke(app, ["queue", "create", "test-queue"])
        result = runner.invoke(app, ["queue", "list"])
        assert result.exit_code == 0
        assert "test-queue" in result.output

    def test_queue_stats(self, mock_sqs):
        runner.invoke(app, ["queue", "create", "my-queue"])
        result = runner.invoke(app, ["queue", "stats", "my-queue"])
        assert result.exit_code == 0
        assert "Messages Available" in result.output

    def test_queue_stats_not_found(self, mock_sqs):
        result = runner.invoke(app, ["queue", "stats", "nonexistent"])
        assert result.exit_code == 1

    def test_queue_purge(self, mock_sqs):
        runner.invoke(app, ["queue", "create", "my-queue"])
        result = runner.invoke(app, ["queue", "purge", "my-queue"])
        assert result.exit_code == 0
        assert "purged" in result.output

    def test_queue_purge_not_found(self, mock_sqs):
        result = runner.invoke(app, ["queue", "purge", "nonexistent"])
        assert result.exit_code == 1

    def test_queue_delete(self, mock_sqs):
        runner.invoke(app, ["queue", "create", "my-queue"])
        result = runner.invoke(app, ["queue", "delete", "my-queue"])
        assert result.exit_code == 0
        assert "deleted" in result.output

    def test_queue_delete_not_found(self, mock_sqs):
        result = runner.invoke(app, ["queue", "delete", "nonexistent"])
        assert result.exit_code == 1


class TestCLIStatsCommand:
    def test_stats_empty(self, mock_sqs):
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "No queues" in result.output

    def test_stats_with_queues(self, mock_sqs):
        runner.invoke(app, ["queue", "create", "emails"])
        runner.invoke(app, ["queue", "create", "images"])
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0
        assert "emails" in result.output
        assert "images" in result.output


class TestCLIDLQCommands:
    def test_dlq_not_found(self, mock_sqs):
        result = runner.invoke(app, ["queue", "dlq", "nonexistent"])
        assert result.exit_code == 1
        assert "No DLQ" in result.output
