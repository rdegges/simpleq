"""Shared test fixtures using moto for SQS mocking."""

from __future__ import annotations

import os

import boto3
import pytest
from moto import mock_aws

from simpleq import SimpleQ
from simpleq.config import Config
from simpleq.cost import CostTracker
from simpleq.queue import Queue


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set fake AWS credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    # Clear any endpoint URL so moto intercepts calls
    monkeypatch.delenv("SIMPLEQ_ENDPOINT_URL", raising=False)


@pytest.fixture
def mock_sqs():
    """Activate moto's AWS mock for the duration of a test."""
    with mock_aws():
        yield


@pytest.fixture
def sq(mock_sqs):
    """A SimpleQ instance with mocked SQS."""
    return SimpleQ()


@pytest.fixture
def sq_with_dlq(mock_sqs):
    """A SimpleQ instance with DLQ enabled."""
    return SimpleQ(dead_letter_queue=True)


@pytest.fixture
def config():
    """A default Config."""
    return Config()


@pytest.fixture
def sqs_client(mock_sqs):
    """A raw boto3 SQS client for test assertions."""
    return boto3.client("sqs", region_name="us-east-1")


@pytest.fixture
def test_queue(mock_sqs, config):
    """A Queue instance pointing at a mocked SQS queue."""
    q = Queue(name="test-queue", config=config, cost_tracker=CostTracker())
    return q
