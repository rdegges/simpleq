"""Configuration loading and environment detection for SimpleQ."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlparse

from simpleq.exceptions import QueueValidationError
from simpleq.queue import normalize_queue_name

BackoffStrategy = Literal["constant", "linear", "exponential", "exponential_jitter"]


def _validate_int_range(
    *,
    name: str,
    value: int,
    minimum: int,
    maximum: int | None = None,
) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer.")
    if value < minimum:
        if maximum is None:
            raise ValueError(f"{name} must be at least {minimum}.")
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")


def _validate_non_negative_float(*, name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} must be a number.")
    if value < 0:
        raise ValueError(f"{name} must be non-negative.")


def _bool_env(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"Unsupported boolean value for {name}: {value!r}. "
        "Use one of: 1, 0, true, false, yes, no, on, off."
    )


def _coalesce_int(explicit: int | None, env_name: str, default: int) -> int:
    if explicit is not None:
        return explicit
    value = os.getenv(env_name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"Invalid integer for {env_name}: {value!r}.") from exc


def _coalesce_float(explicit: float | None, env_name: str, default: float) -> float:
    if explicit is not None:
        return explicit
    value = os.getenv(env_name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid float for {env_name}: {value!r}.") from exc


def _endpoint_reachable(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.hostname is None:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=0.1):
            return True
    except OSError:
        return False


def _normalize_endpoint_url(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("endpoint_url must be a string.")
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


def _resolve_region(*, explicit: str | None, default: str) -> str:
    if explicit is not None:
        if not isinstance(explicit, str):
            raise ValueError("region must be a string.")
        normalized_explicit = explicit.strip()
        if not normalized_explicit:
            raise ValueError("region must be non-empty.")
        return normalized_explicit

    for env_name in ("SIMPLEQ_REGION", "AWS_REGION", "AWS_DEFAULT_REGION"):
        value = os.getenv(env_name)
        if value is None:
            continue
        normalized = value.strip()
        if normalized:
            return normalized

    return default


def _localstack_endpoint_from_hostname(hostname: str) -> str:
    normalized = hostname.strip()
    parsed = urlparse(normalized)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"

    parsed_host = urlparse(f"//{normalized}")
    if parsed_host.hostname is None:
        return f"http://{normalized}:4566"
    if parsed_host.port is not None:
        return f"http://{parsed_host.netloc}"
    return f"http://{parsed_host.netloc}:4566"


def _validate_endpoint_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            f"endpoint_url must be a valid HTTP or HTTPS URL, got: {value!r}."
        )


def resolve_endpoint_url_from_env() -> str | None:
    """Return an explicitly configured SQS endpoint from environment variables."""
    for env_name in (
        "SIMPLEQ_ENDPOINT_URL",
        "AWS_ENDPOINT_URL_SQS",
        "AWS_ENDPOINT_URL",
    ):
        value = os.getenv(env_name)
        if value is None:
            continue
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def detect_localstack_endpoint() -> str | None:
    """Return a sensible LocalStack endpoint for dev and CI environments."""
    if endpoint := resolve_endpoint_url_from_env():
        return endpoint

    auto_localstack = _bool_env("SIMPLEQ_AUTO_LOCALSTACK")
    if auto_localstack is False:
        return None

    if hostname := os.getenv("LOCALSTACK_HOSTNAME"):
        return _localstack_endpoint_from_hostname(hostname)

    if hostname := os.getenv("LOCALSTACK_HOST"):
        return _localstack_endpoint_from_hostname(hostname)

    env_name = os.getenv("SIMPLEQ_ENV", "").strip().lower()
    inside_docker = Path("/.dockerenv").exists()

    if os.getenv("CI"):
        return "http://localhost:4566"

    if env_name == "test":
        return "http://localhost:4566"

    if inside_docker and env_name in {"development", "dev", "test"}:
        return "http://localstack:4566"

    if _endpoint_reachable("http://localhost:4566"):
        return "http://localhost:4566"

    if inside_docker and _endpoint_reachable("http://localstack:4566"):
        return "http://localstack:4566"

    return None


@dataclass(slots=True)
class SimpleQConfig:
    """Resolved runtime configuration for SimpleQ."""

    region: str = "us-east-1"
    endpoint_url: str | None = None
    batch_size: int = 10
    wait_seconds: int = 20
    poll_interval: float = 1.0
    receive_timeout_seconds: float | None = None
    visibility_timeout: int = 300
    concurrency: int = 10
    graceful_shutdown_timeout: int = 30
    max_retries: int = 3
    backoff_strategy: BackoffStrategy = "exponential"
    retry_jitter_min_seconds: int = 1
    enable_cost_tracking: bool = True
    enable_metrics: bool = True
    enable_tracing: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    sqs_price_per_million: float = 0.40
    default_queue_name: str = "default"

    @classmethod
    def from_overrides(
        cls,
        *,
        region: str | None = None,
        endpoint_url: str | None = None,
        batch_size: int | None = None,
        wait_seconds: int | None = None,
        poll_interval: float | None = None,
        receive_timeout_seconds: float | None = None,
        visibility_timeout: int | None = None,
        concurrency: int | None = None,
        graceful_shutdown_timeout: int | None = None,
        max_retries: int | None = None,
        backoff_strategy: BackoffStrategy | None = None,
        retry_jitter_min_seconds: int | None = None,
        enable_cost_tracking: bool | None = None,
        enable_metrics: bool | None = None,
        enable_tracing: bool | None = None,
        log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] | None = None,
        sqs_price_per_million: float | None = None,
        default_queue_name: str | None = None,
    ) -> SimpleQConfig:
        """Resolve configuration using explicit values, then env vars, then defaults."""
        config = cls()

        config.region = _resolve_region(explicit=region, default=config.region)
        config.endpoint_url = (
            _normalize_endpoint_url(endpoint_url)
            or resolve_endpoint_url_from_env()
            or detect_localstack_endpoint()
        )
        config.batch_size = _coalesce_int(
            batch_size, "SIMPLEQ_BATCH_SIZE", config.batch_size
        )
        config.wait_seconds = _coalesce_int(
            wait_seconds, "SIMPLEQ_WAIT_SECONDS", config.wait_seconds
        )
        config.poll_interval = _coalesce_float(
            poll_interval,
            "SIMPLEQ_POLL_INTERVAL",
            config.poll_interval,
        )
        if receive_timeout_seconds is not None:
            config.receive_timeout_seconds = receive_timeout_seconds
        else:
            receive_timeout_seconds_env = os.getenv("SIMPLEQ_RECEIVE_TIMEOUT_SECONDS")
            if receive_timeout_seconds_env is None:
                config.receive_timeout_seconds = None
            else:
                try:
                    config.receive_timeout_seconds = float(receive_timeout_seconds_env)
                except ValueError as exc:
                    raise ValueError(
                        "Invalid float for SIMPLEQ_RECEIVE_TIMEOUT_SECONDS: "
                        f"{receive_timeout_seconds_env!r}."
                    ) from exc
        config.visibility_timeout = _coalesce_int(
            visibility_timeout,
            "SIMPLEQ_VISIBILITY_TIMEOUT",
            config.visibility_timeout,
        )
        config.concurrency = _coalesce_int(
            concurrency, "SIMPLEQ_CONCURRENCY", config.concurrency
        )
        config.graceful_shutdown_timeout = _coalesce_int(
            graceful_shutdown_timeout,
            "SIMPLEQ_GRACEFUL_SHUTDOWN_TIMEOUT",
            config.graceful_shutdown_timeout,
        )
        config.max_retries = _coalesce_int(
            max_retries, "SIMPLEQ_MAX_RETRIES", config.max_retries
        )
        config.backoff_strategy = cast_backoff_strategy(
            backoff_strategy
            or os.getenv("SIMPLEQ_BACKOFF_STRATEGY")
            or config.backoff_strategy
        )
        config.retry_jitter_min_seconds = _coalesce_int(
            retry_jitter_min_seconds,
            "SIMPLEQ_RETRY_JITTER_MIN_SECONDS",
            config.retry_jitter_min_seconds,
        )
        config.enable_cost_tracking = resolve_bool(
            explicit=enable_cost_tracking,
            env_name="SIMPLEQ_COST_TRACKING",
            default=config.enable_cost_tracking,
            option_name="enable_cost_tracking",
        )
        config.enable_metrics = resolve_bool(
            explicit=enable_metrics,
            env_name="SIMPLEQ_ENABLE_METRICS",
            default=config.enable_metrics,
            option_name="enable_metrics",
        )
        config.enable_tracing = resolve_bool(
            explicit=enable_tracing,
            env_name="SIMPLEQ_ENABLE_TRACING",
            default=config.enable_tracing,
            option_name="enable_tracing",
        )
        config.log_level = cast_log_level(
            log_level or os.getenv("SIMPLEQ_LOG_LEVEL") or config.log_level
        )
        config.sqs_price_per_million = _coalesce_float(
            sqs_price_per_million,
            "SIMPLEQ_SQS_PRICE_PER_MILLION",
            config.sqs_price_per_million,
        )
        if default_queue_name is not None:
            config.default_queue_name = default_queue_name
        else:
            config.default_queue_name = (
                os.getenv("SIMPLEQ_DEFAULT_QUEUE") or config.default_queue_name
            )
        validate_config(config)
        return config


def validate_config(config: SimpleQConfig) -> None:
    """Validate resolved configuration values."""
    if not isinstance(config.region, str):
        raise ValueError("region must be a string.")
    if not config.region.strip():
        raise ValueError("region must be non-empty.")
    config.region = config.region.strip()
    _validate_int_range(
        name="batch_size", value=config.batch_size, minimum=1, maximum=10
    )
    _validate_int_range(
        name="wait_seconds",
        value=config.wait_seconds,
        minimum=0,
        maximum=20,
    )
    _validate_non_negative_float(name="poll_interval", value=config.poll_interval)
    if config.receive_timeout_seconds is not None:
        _validate_non_negative_float(
            name="receive_timeout_seconds",
            value=config.receive_timeout_seconds,
        )
        if config.receive_timeout_seconds <= 0:
            raise ValueError("receive_timeout_seconds must be greater than 0.")
    _validate_int_range(
        name="visibility_timeout",
        value=config.visibility_timeout,
        minimum=0,
        maximum=43_200,
    )
    _validate_int_range(name="concurrency", value=config.concurrency, minimum=1)
    _validate_int_range(
        name="graceful_shutdown_timeout",
        value=config.graceful_shutdown_timeout,
        minimum=0,
    )
    _validate_int_range(name="max_retries", value=config.max_retries, minimum=0)
    _validate_int_range(
        name="retry_jitter_min_seconds",
        value=config.retry_jitter_min_seconds,
        minimum=1,
    )
    _validate_non_negative_float(
        name="sqs_price_per_million",
        value=config.sqs_price_per_million,
    )
    if config.endpoint_url is not None:
        _validate_endpoint_url(config.endpoint_url)
    if not isinstance(config.default_queue_name, str):
        raise ValueError("default_queue_name must be a string.")
    normalized_default_queue_name = config.default_queue_name.strip()
    if not normalized_default_queue_name:
        raise ValueError("default_queue_name must be non-empty.")
    try:
        normalize_queue_name(
            normalized_default_queue_name,
            fifo=normalized_default_queue_name.endswith(".fifo"),
        )
    except QueueValidationError as exc:
        raise ValueError(f"Invalid default_queue_name: {exc}") from exc
    config.default_queue_name = normalized_default_queue_name


def resolve_bool(
    *,
    explicit: bool | None,
    env_name: str,
    default: bool,
    option_name: str | None = None,
) -> bool:
    """Resolve a boolean from explicit input, env, and a default."""
    if explicit is not None:
        if not isinstance(explicit, bool):
            field_name = option_name or env_name
            raise ValueError(f"{field_name} must be a boolean.")
        return explicit
    from_env = _bool_env(env_name)
    if from_env is None:
        return default
    return from_env


def cast_backoff_strategy(value: str) -> BackoffStrategy:
    """Validate a backoff strategy string."""
    if not isinstance(value, str):
        raise ValueError("backoff_strategy must be a string.")
    normalized = value.strip().lower()
    if normalized not in {
        "constant",
        "linear",
        "exponential",
        "exponential_jitter",
    }:
        raise ValueError(f"Unsupported backoff strategy: {value}")
    return cast("BackoffStrategy", normalized)


def cast_log_level(value: str) -> Literal["DEBUG", "INFO", "WARNING", "ERROR"]:
    """Validate a log level string."""
    if not isinstance(value, str):
        raise ValueError("log_level must be a string.")
    normalized = value.strip().upper()
    if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise ValueError(f"Unsupported log level: {value}")
    return cast("Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']", normalized)
