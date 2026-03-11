"""Unit tests for configuration behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from simpleq.config import (
    SimpleQConfig,
    cast_backoff_strategy,
    cast_log_level,
    detect_localstack_endpoint,
    resolve_bool,
)


def test_detect_localstack_uses_explicit_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLEQ_ENDPOINT_URL", "http://localhost:9999")
    assert detect_localstack_endpoint() == "http://localhost:9999"


def test_from_overrides_uses_service_specific_aws_endpoint_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL_SQS", "http://localhost:4567")

    config = SimpleQConfig.from_overrides()

    assert config.endpoint_url == "http://localhost:4567"


def test_from_overrides_uses_global_aws_endpoint_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localhost:4568")

    config = SimpleQConfig.from_overrides()

    assert config.endpoint_url == "http://localhost:4568"


def test_from_overrides_prefers_simpleq_endpoint_over_aws_endpoint_envs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_ENDPOINT_URL", "http://localhost:9999")
    monkeypatch.setenv("AWS_ENDPOINT_URL_SQS", "http://localhost:4567")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "http://localhost:4568")

    config = SimpleQConfig.from_overrides()

    assert config.endpoint_url == "http://localhost:9999"


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


def test_from_overrides_normalizes_explicit_endpoint_whitespace() -> None:
    config = SimpleQConfig.from_overrides(endpoint_url="  http://localhost:4566  ")

    assert config.endpoint_url == "http://localhost:4566"


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
    monkeypatch.setenv("FEATURE_FLAG", "off")
    assert resolve_bool(explicit=None, env_name="FEATURE_FLAG", default=True) is False
    assert cast_log_level("ERROR") == "ERROR"
    with pytest.raises(ValueError):
        cast_log_level("TRACE")


def test_numeric_env_and_explicit_float_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_BATCH_SIZE", "8")
    monkeypatch.setenv("SIMPLEQ_SQS_PRICE_PER_MILLION", "0.9")
    from_env = SimpleQConfig.from_overrides()
    assert from_env.batch_size == 8
    assert from_env.sqs_price_per_million == 0.9

    explicit = SimpleQConfig.from_overrides(sqs_price_per_million=0.2)
    assert explicit.sqs_price_per_million == 0.2


def test_from_overrides_rejects_invalid_boolean_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_ENABLE_METRICS", "maybe")
    with pytest.raises(ValueError, match="Unsupported boolean value"):
        SimpleQConfig.from_overrides()


def test_from_overrides_rejects_invalid_integer_env_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_CONCURRENCY", "many")

    with pytest.raises(ValueError, match="Invalid integer for SIMPLEQ_CONCURRENCY"):
        SimpleQConfig.from_overrides()


def test_from_overrides_rejects_invalid_float_env_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_SQS_PRICE_PER_MILLION", "cheap")

    with pytest.raises(
        ValueError, match="Invalid float for SIMPLEQ_SQS_PRICE_PER_MILLION"
    ):
        SimpleQConfig.from_overrides()


def test_from_overrides_rejects_invalid_endpoint_url_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_ENDPOINT_URL", "localhost:4566")

    with pytest.raises(ValueError, match="endpoint_url must be a valid HTTP or HTTPS"):
        SimpleQConfig.from_overrides()


def test_from_overrides_rejects_invalid_endpoint_url_explicit() -> None:
    with pytest.raises(ValueError, match="endpoint_url must be a valid HTTP or HTTPS"):
        SimpleQConfig.from_overrides(endpoint_url="localhost:4566")


def test_from_overrides_normalizes_case_for_string_enums(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_LOG_LEVEL", "debug")
    monkeypatch.setenv("SIMPLEQ_BACKOFF_STRATEGY", "LINEAR")

    config = SimpleQConfig.from_overrides()

    assert config.log_level == "DEBUG"
    assert config.backoff_strategy == "linear"


def test_cast_backoff_strategy_and_log_level_strip_whitespace() -> None:
    assert cast_backoff_strategy("  exponential  ") == "exponential"
    assert cast_log_level(" warning ") == "WARNING"


def test_from_overrides_normalizes_default_queue_name_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_DEFAULT_QUEUE", "  events.fifo  ")

    config = SimpleQConfig.from_overrides()

    assert config.default_queue_name == "events.fifo"


@pytest.mark.parametrize(
    "value",
    [
        "   ",
        "bad queue name",
        "orders.fifo.extra",
    ],
)
def test_from_overrides_rejects_invalid_default_queue_name(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("SIMPLEQ_DEFAULT_QUEUE", value)

    with pytest.raises(ValueError, match="default_queue_name"):
        SimpleQConfig.from_overrides()


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"batch_size": 0}, "batch_size must be between 1 and 10"),
        ({"batch_size": 11}, "batch_size must be between 1 and 10"),
        ({"wait_seconds": -1}, "wait_seconds must be between 0 and 20"),
        ({"wait_seconds": 21}, "wait_seconds must be between 0 and 20"),
        (
            {"visibility_timeout": -1},
            "visibility_timeout must be between 0 and 43200",
        ),
        (
            {"visibility_timeout": 43_201},
            "visibility_timeout must be between 0 and 43200",
        ),
        ({"concurrency": 0}, "concurrency must be at least 1"),
    ],
)
def test_from_overrides_rejects_invalid_numeric_ranges(
    kwargs: dict[str, int],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        SimpleQConfig.from_overrides(**kwargs)
