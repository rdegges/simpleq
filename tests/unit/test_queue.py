"""Unit tests for queue behavior."""

from __future__ import annotations

import pytest

from simpleq import SimpleQ
from simpleq.exceptions import QueueValidationError
from simpleq.job import Job
from simpleq.queue import BatchEntry, encode_message_attributes, normalize_queue_name


def test_normalize_queue_name_validates_fifo_suffix() -> None:
    assert normalize_queue_name("emails", fifo=False) == "emails"
    assert normalize_queue_name("orders.fifo", fifo=True) == "orders.fifo"
    with pytest.raises(QueueValidationError):
        normalize_queue_name("emails", fifo=True)
    with pytest.raises(QueueValidationError):
        normalize_queue_name("orders.fifo", fifo=False)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "name with spaces",
        "name/with/slash",
        "name:with:colon",
        "name*with*wildcards",
    ],
)
def test_normalize_queue_name_rejects_invalid_characters(name: str) -> None:
    with pytest.raises(QueueValidationError):
        normalize_queue_name(name, fifo=False)


def test_normalize_queue_name_rejects_names_longer_than_80_characters() -> None:
    long_name = "a" * 81
    with pytest.raises(QueueValidationError):
        normalize_queue_name(long_name, fifo=False)


def test_normalize_queue_name_rejects_fifo_base_names_longer_than_limit() -> None:
    too_long_fifo = ("a" * 76) + ".fifo"
    with pytest.raises(QueueValidationError):
        normalize_queue_name(too_long_fifo, fifo=True)


def test_queue_derives_dlq_name() -> None:
    simpleq = SimpleQ()
    assert simpleq.queue("emails", dlq=True).dlq_name == "emails-dlq"
    assert (
        simpleq.queue("orders.fifo", fifo=True, dlq=True).dlq_name == "orders-dlq.fifo"
    )


@pytest.mark.parametrize("max_retries", [0, -1, 1001])
def test_queue_rejects_invalid_dlq_max_retries(max_retries: int) -> None:
    with pytest.raises(
        QueueValidationError, match="DLQ max_retries must be between 1 and 1000"
    ):
        SimpleQ().queue("emails", dlq=True, max_retries=max_retries)


def test_queue_allows_non_dlq_zero_max_retries() -> None:
    queue = SimpleQ().queue("emails", dlq=False, max_retries=0)
    assert queue.max_retries == 0


def test_queue_validates_fifo_options() -> None:
    queue = SimpleQ().queue("orders.fifo", fifo=True, dlq=True)
    with pytest.raises(QueueValidationError):
        queue._validate_message_options(
            delay_seconds=1, message_group_id="group", deduplication_id="dedup"
        )
    with pytest.raises(QueueValidationError):
        queue._validate_message_options(
            delay_seconds=0, message_group_id=None, deduplication_id="dedup"
        )
    with pytest.raises(QueueValidationError):
        queue._validate_message_options(
            delay_seconds=0, message_group_id="group", deduplication_id=None
        )


@pytest.mark.parametrize(
    ("message_group_id", "deduplication_id", "message"),
    [
        ("", "dedup", "message_group_id must be a non-empty string"),
        ("group", "", "deduplication_id must be a non-empty string"),
        ("g" * 129, "dedup", "message_group_id must be 128 characters or fewer"),
        ("group", "d" * 129, "deduplication_id must be 128 characters or fewer"),
    ],
)
def test_queue_validates_fifo_routing_identifiers(
    message_group_id: str,
    deduplication_id: str,
    message: str,
) -> None:
    queue = SimpleQ().queue("orders.fifo", fifo=True, dlq=True)
    with pytest.raises(QueueValidationError, match=message):
        queue._validate_message_options(
            delay_seconds=0,
            message_group_id=message_group_id,
            deduplication_id=deduplication_id,
        )


def test_encode_message_attributes() -> None:
    assert encode_message_attributes({"source": "tests"}) == {
        "source": {"DataType": "String", "StringValue": "tests"}
    }


def test_encode_message_attributes_rejects_more_than_ten_attributes() -> None:
    attributes = {f"k{i}": "value" for i in range(11)}
    with pytest.raises(QueueValidationError, match="at most 10"):
        encode_message_attributes(attributes)


@pytest.mark.parametrize(
    ("attributes", "message"),
    [
        ({"": "value"}, "non-empty"),
        ({"bad key": "value"}, "letters, numbers, hyphens, underscores, or periods"),
        ({"k" * 257: "value"}, "between 1 and 256"),
    ],
)
def test_encode_message_attributes_rejects_invalid_attribute_names(
    attributes: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(QueueValidationError, match=message):
        encode_message_attributes(attributes)


def test_encode_message_attributes_rejects_non_string_value() -> None:
    with pytest.raises(QueueValidationError, match="must be strings"):
        encode_message_attributes({"source": "tests", "attempt": 1})  # type: ignore[arg-type]


def test_encode_message_attributes_allows_large_values_within_sqs_limits() -> None:
    value = "a" * 2048
    assert encode_message_attributes({"source": value}) == {
        "source": {"DataType": "String", "StringValue": value}
    }


def test_encode_message_attributes_rejects_values_larger_than_256_kib() -> None:
    with pytest.raises(QueueValidationError, match="at most 262144 bytes"):
        encode_message_attributes({"source": "a" * (262_144 + 1)})


@pytest.mark.asyncio
async def test_enqueue_many_rejects_large_batches() -> None:
    simpleq = SimpleQ()
    queue = simpleq.queue("emails")
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("a",),
        kwargs={},
        queue_name="emails",
    )
    entries = [BatchEntry(job=job) for _ in range(11)]
    with pytest.raises(QueueValidationError):
        await queue.enqueue_many(entries)
