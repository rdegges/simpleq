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


def test_detect_localstack_uses_localstack_host_when_hostname_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALSTACK_HOST", "localstack")

    assert detect_localstack_endpoint() == "http://localstack:4566"


def test_detect_localstack_ignores_blank_localstack_hostname_and_uses_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALSTACK_HOSTNAME", "   ")
    monkeypatch.setenv("LOCALSTACK_HOST", "localstack")

    assert detect_localstack_endpoint() == "http://localstack:4566"


def test_detect_localstack_ignores_blank_localstack_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALSTACK_HOST", "   ")
    monkeypatch.setattr("simpleq.config._endpoint_reachable", lambda _url: False)

    assert detect_localstack_endpoint() is None


@pytest.mark.parametrize(
    ("hostname", "expected"),
    [
        ("localstack:4577", "http://localstack:4577"),
        ("https://localstack.internal:8443", "https://localstack.internal:8443"),
        (
            " http://localhost.localstack.cloud:4566 ",
            "http://localhost.localstack.cloud:4566",
        ),
    ],
)
def test_detect_localstack_normalizes_localstack_hostname_values(
    monkeypatch: pytest.MonkeyPatch,
    hostname: str,
    expected: str,
) -> None:
    monkeypatch.setenv("LOCALSTACK_HOSTNAME", hostname)

    assert detect_localstack_endpoint() == expected


def test_detect_localstack_prefers_hostname_over_localstack_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALSTACK_HOSTNAME", "https://preferred.localstack:8443")
    monkeypatch.setenv("LOCALSTACK_HOST", "fallback.localstack:4566")

    assert detect_localstack_endpoint() == "https://preferred.localstack:8443"


def test_detect_localstack_uses_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    assert detect_localstack_endpoint() == "http://localhost:4566"


def test_detect_localstack_can_disable_auto_detection_in_ci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("SIMPLEQ_AUTO_LOCALSTACK", "false")

    assert detect_localstack_endpoint() is None


def test_detect_localstack_rejects_invalid_auto_detection_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_AUTO_LOCALSTACK", "sometimes")

    with pytest.raises(ValueError, match="Unsupported boolean value"):
        detect_localstack_endpoint()


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


def test_from_overrides_uses_simpleq_region_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_REGION", "eu-central-1")

    config = SimpleQConfig.from_overrides()

    assert config.region == "eu-central-1"


def test_from_overrides_normalizes_explicit_region_whitespace() -> None:
    config = SimpleQConfig.from_overrides(region="  eu-west-1  ")

    assert config.region == "eu-west-1"


def test_from_overrides_ignores_blank_region_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_REGION", "   ")
    monkeypatch.setenv("AWS_REGION", "us-west-1")

    config = SimpleQConfig.from_overrides()

    assert config.region == "us-west-1"


def test_from_overrides_rejects_empty_explicit_region() -> None:
    with pytest.raises(ValueError, match="region must be non-empty"):
        SimpleQConfig.from_overrides(region="   ")


def test_from_overrides_prefers_simpleq_region_over_aws_region_envs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_REGION", "eu-central-1")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-southeast-2")

    config = SimpleQConfig.from_overrides()

    assert config.region == "eu-central-1"


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
    monkeypatch.setenv("SIMPLEQ_POLL_INTERVAL", "0.25")
    from_env = SimpleQConfig.from_overrides()
    assert from_env.batch_size == 8
    assert from_env.sqs_price_per_million == 0.9
    assert from_env.poll_interval == 0.25
    assert from_env.receive_timeout_seconds is None

    explicit = SimpleQConfig.from_overrides(sqs_price_per_million=0.2)
    assert explicit.sqs_price_per_million == 0.2


def test_from_overrides_ignores_blank_numeric_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_BATCH_SIZE", "   ")
    monkeypatch.setenv("SIMPLEQ_POLL_INTERVAL", "")
    monkeypatch.setenv("SIMPLEQ_SQS_PRICE_PER_MILLION", " ")

    config = SimpleQConfig.from_overrides()

    assert config.batch_size == 10
    assert config.poll_interval == 1.0
    assert config.sqs_price_per_million == 0.40


def test_from_overrides_reads_sqs_max_pool_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_SQS_MAX_POOL_CONNECTIONS", "32")

    config = SimpleQConfig.from_overrides()

    assert config.sqs_max_pool_connections == 32


def test_from_overrides_prefers_explicit_sqs_max_pool_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_SQS_MAX_POOL_CONNECTIONS", "32")

    config = SimpleQConfig.from_overrides(sqs_max_pool_connections=48)

    assert config.sqs_max_pool_connections == 48


def test_from_overrides_prefers_explicit_poll_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_POLL_INTERVAL", "0.25")

    config = SimpleQConfig.from_overrides(poll_interval=0.1)

    assert config.poll_interval == 0.1


def test_from_overrides_reads_receive_timeout_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_RECEIVE_TIMEOUT_SECONDS", "45")

    config = SimpleQConfig.from_overrides()

    assert config.receive_timeout_seconds == 45.0


def test_from_overrides_ignores_blank_receive_timeout_seconds_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_RECEIVE_TIMEOUT_SECONDS", "   ")

    config = SimpleQConfig.from_overrides()

    assert config.receive_timeout_seconds is None


def test_from_overrides_prefers_explicit_receive_timeout_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_RECEIVE_TIMEOUT_SECONDS", "45")

    config = SimpleQConfig.from_overrides(receive_timeout_seconds=7.5)

    assert config.receive_timeout_seconds == 7.5


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        (
            {"receive_timeout_seconds": -1},
            "receive_timeout_seconds must be non-negative",
        ),
        (
            {"receive_timeout_seconds": 0},
            "receive_timeout_seconds must be greater than 0",
        ),
        ({"receive_timeout_seconds": True}, "receive_timeout_seconds must be a number"),
    ],
)
def test_from_overrides_rejects_invalid_receive_timeout_seconds(
    kwargs: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        SimpleQConfig.from_overrides(**kwargs)


def test_from_overrides_rejects_invalid_receive_timeout_seconds_env_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_RECEIVE_TIMEOUT_SECONDS", "forever")

    with pytest.raises(
        ValueError,
        match="Invalid float for SIMPLEQ_RECEIVE_TIMEOUT_SECONDS",
    ):
        SimpleQConfig.from_overrides()


def test_from_overrides_rejects_invalid_boolean_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_ENABLE_METRICS", "maybe")
    with pytest.raises(ValueError, match="Unsupported boolean value"):
        SimpleQConfig.from_overrides()


def test_from_overrides_ignores_blank_boolean_env_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_COST_TRACKING", "   ")
    monkeypatch.setenv("SIMPLEQ_ENABLE_METRICS", "")
    monkeypatch.setenv("SIMPLEQ_ENABLE_TRACING", " ")

    config = SimpleQConfig.from_overrides()

    assert config.enable_cost_tracking is True
    assert config.enable_metrics is True
    assert config.enable_tracing is False


def test_from_overrides_rejects_invalid_integer_env_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_CONCURRENCY", "many")

    with pytest.raises(ValueError, match="Invalid integer for SIMPLEQ_CONCURRENCY"):
        SimpleQConfig.from_overrides()


def test_from_overrides_rejects_invalid_sqs_max_pool_connections_env_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_SQS_MAX_POOL_CONNECTIONS", "many")

    with pytest.raises(
        ValueError,
        match="Invalid integer for SIMPLEQ_SQS_MAX_POOL_CONNECTIONS",
    ):
        SimpleQConfig.from_overrides()


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"concurrency": True}, "concurrency must be an integer"),
        ({"batch_size": 5.0}, "batch_size must be an integer"),
        ({"max_retries": False}, "max_retries must be an integer"),
    ],
)
def test_from_overrides_rejects_non_integer_explicit_numeric_values(
    kwargs: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        SimpleQConfig.from_overrides(**kwargs)


def test_from_overrides_rejects_invalid_float_env_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_SQS_PRICE_PER_MILLION", "cheap")

    with pytest.raises(
        ValueError, match="Invalid float for SIMPLEQ_SQS_PRICE_PER_MILLION"
    ):
        SimpleQConfig.from_overrides()


def test_from_overrides_rejects_invalid_poll_interval_env_with_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_POLL_INTERVAL", "fast")

    with pytest.raises(ValueError, match="Invalid float for SIMPLEQ_POLL_INTERVAL"):
        SimpleQConfig.from_overrides()


def test_from_overrides_rejects_boolean_explicit_float_override() -> None:
    with pytest.raises(ValueError, match="sqs_price_per_million must be a number"):
        SimpleQConfig.from_overrides(sqs_price_per_million=True)


def test_from_overrides_rejects_invalid_endpoint_url_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_ENDPOINT_URL", "localhost:4566")

    with pytest.raises(ValueError, match="endpoint_url must be a valid HTTP or HTTPS"):
        SimpleQConfig.from_overrides()


def test_from_overrides_rejects_invalid_endpoint_url_explicit() -> None:
    with pytest.raises(ValueError, match="endpoint_url must be a valid HTTP or HTTPS"):
        SimpleQConfig.from_overrides(endpoint_url="localhost:4566")


def test_from_overrides_rejects_non_string_region() -> None:
    with pytest.raises(ValueError, match="region must be a string"):
        SimpleQConfig.from_overrides(region=123)  # type: ignore[arg-type]


def test_from_overrides_rejects_non_string_backoff_strategy() -> None:
    with pytest.raises(ValueError, match="backoff_strategy must be a string"):
        SimpleQConfig.from_overrides(backoff_strategy=123)  # type: ignore[arg-type]


def test_from_overrides_rejects_non_string_log_level() -> None:
    with pytest.raises(ValueError, match="log_level must be a string"):
        SimpleQConfig.from_overrides(log_level=123)  # type: ignore[arg-type]


def test_from_overrides_rejects_non_string_default_queue_name() -> None:
    with pytest.raises(ValueError, match="default_queue_name must be a string"):
        SimpleQConfig.from_overrides(default_queue_name=123)  # type: ignore[arg-type]


def test_from_overrides_rejects_non_boolean_explicit_boolean_flags() -> None:
    with pytest.raises(ValueError, match="enable_metrics must be a boolean"):
        SimpleQConfig.from_overrides(enable_metrics=1)  # type: ignore[arg-type]


def test_from_overrides_normalizes_case_for_string_enums(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_LOG_LEVEL", "debug")
    monkeypatch.setenv("SIMPLEQ_BACKOFF_STRATEGY", "LINEAR")

    config = SimpleQConfig.from_overrides()

    assert config.log_level == "DEBUG"
    assert config.backoff_strategy == "linear"


def test_from_overrides_reads_retry_jitter_min_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_RETRY_JITTER_MIN_SECONDS", "4")

    config = SimpleQConfig.from_overrides()

    assert config.retry_jitter_min_seconds == 4


def test_from_overrides_prefers_explicit_retry_jitter_min_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_RETRY_JITTER_MIN_SECONDS", "4")

    config = SimpleQConfig.from_overrides(retry_jitter_min_seconds=2)

    assert config.retry_jitter_min_seconds == 2


def test_cast_backoff_strategy_and_log_level_strip_whitespace() -> None:
    assert cast_backoff_strategy("  exponential  ") == "exponential"
    assert cast_backoff_strategy(" Exponential_Jitter ") == "exponential_jitter"
    assert cast_log_level(" warning ") == "WARNING"


def test_from_overrides_normalizes_default_queue_name_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_DEFAULT_QUEUE", "  events.fifo  ")

    config = SimpleQConfig.from_overrides()

    assert config.default_queue_name == "events.fifo"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://sqs.us-east-1.amazonaws.com/123456789012/events", "events"),
        (
            "https://sqs.us-east-1.amazonaws.com/123456789012/orders%2Efifo",
            "orders.fifo",
        ),
        ("arn:aws:sqs:us-east-1:123456789012:emails", "emails"),
        ("arn:aws-us-gov:sqs:us-gov-west-1:123456789012:events.fifo", "events.fifo"),
    ],
)
def test_from_overrides_normalizes_default_queue_reference_env(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    expected: str,
) -> None:
    monkeypatch.setenv("SIMPLEQ_DEFAULT_QUEUE", value)

    config = SimpleQConfig.from_overrides()

    assert config.default_queue_name == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://sqs.us-east-1.amazonaws.com/123456789012/events", "events"),
        ("arn:aws:sqs:us-east-1:123456789012:events.fifo", "events.fifo"),
    ],
)
def test_from_overrides_normalizes_explicit_default_queue_reference(
    value: str,
    expected: str,
) -> None:
    config = SimpleQConfig.from_overrides(default_queue_name=value)

    assert config.default_queue_name == expected


def test_from_overrides_ignores_blank_default_queue_name_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SIMPLEQ_DEFAULT_QUEUE", "   ")

    config = SimpleQConfig.from_overrides()

    assert config.default_queue_name == "default"


@pytest.mark.parametrize("value", ["", "   "])
def test_from_overrides_rejects_explicit_empty_default_queue_name(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("SIMPLEQ_DEFAULT_QUEUE", "env-default")

    with pytest.raises(ValueError, match="default_queue_name must be non-empty"):
        SimpleQConfig.from_overrides(default_queue_name=value)


@pytest.mark.parametrize(
    "value",
    [
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
    "value",
    [
        "https://sqs.us-east-1.amazonaws.com/123456789012/not valid",
        "arn:aws:sqs:us-east-1:123456789012:",
    ],
)
def test_from_overrides_rejects_invalid_default_queue_reference(
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
        (
            {"retry_jitter_min_seconds": 0},
            "retry_jitter_min_seconds must be at least 1",
        ),
        (
            {"sqs_max_pool_connections": 0},
            "sqs_max_pool_connections must be at least 1",
        ),
    ],
)
def test_from_overrides_rejects_invalid_numeric_ranges(
    kwargs: dict[str, int],
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        SimpleQConfig.from_overrides(**kwargs)
