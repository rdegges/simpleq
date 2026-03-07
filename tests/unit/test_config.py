"""Unit tests for configuration behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from simpleq.config import (
    SimpleQConfig,
    cast_log_level,
    detect_localstack_endpoint,
    resolve_bool,
)


def test_detect_localstack_uses_explicit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLEQ_ENDPOINT_URL", "http://localhost:9999")
    assert detect_localstack_endpoint() == "http://localhost:9999"


def test_detect_localstack_uses_localstack_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALSTACK_HOSTNAME", "localstack")
    assert detect_localstack_endpoint() == "http://localstack:4566"


def test_detect_localstack_uses_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    assert detect_localstack_endpoint() == "http://localhost:4566"


def test_detect_localstack_uses_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLEQ_ENV", "test")
    assert detect_localstack_endpoint() == "http://localhost:4566"


def test_detect_localstack_uses_docker_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLEQ_ENV", "development")
    monkeypatch.setattr(Path, "exists", lambda self: str(self) == "/.dockerenv")
    assert detect_localstack_endpoint() == "http://localstack:4566"


def test_detect_localstack_uses_reachable_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "simpleq.config._endpoint_reachable", lambda url: url.endswith("4566")
    )
    assert detect_localstack_endpoint() == "http://localhost:4566"


def test_from_overrides_prefers_explicit_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("SIMPLEQ_CONCURRENCY", "99")
    config = SimpleQConfig.from_overrides(region="eu-west-1", concurrency=3)
    assert config.region == "eu-west-1"
    assert config.concurrency == 3


def test_from_overrides_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-2")
    monkeypatch.setenv("SIMPLEQ_LOG_LEVEL", "DEBUG")
    config = SimpleQConfig.from_overrides()
    assert config.region == "ap-southeast-2"
    assert config.log_level == "DEBUG"


def test_from_overrides_rejects_invalid_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_BACKOFF_STRATEGY", "wat")
    with pytest.raises(ValueError):
        SimpleQConfig.from_overrides()


def test_detect_localstack_returns_none_when_not_applicable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("simpleq.config._endpoint_reachable", lambda url: False)
    assert detect_localstack_endpoint() is None


def test_resolve_bool_and_cast_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_FLAG", "true")
    assert resolve_bool(explicit=None, env_name="FEATURE_FLAG", default=False) is True
    assert resolve_bool(explicit=False, env_name="FEATURE_FLAG", default=True) is False
    assert cast_log_level("ERROR") == "ERROR"
    with pytest.raises(ValueError):
        cast_log_level("TRACE")


def test_numeric_env_and_explicit_float_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_BATCH_SIZE", "12")
    monkeypatch.setenv("SIMPLEQ_SQS_PRICE_PER_MILLION", "0.9")
    from_env = SimpleQConfig.from_overrides()
    assert from_env.batch_size == 12
    assert from_env.sqs_price_per_million == 0.9

    explicit = SimpleQConfig.from_overrides(sqs_price_per_million=0.2)
    assert explicit.sqs_price_per_million == 0.2
