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


def test_standard_queue_rejects_fifo_routing_options() -> None:
    queue = SimpleQ().queue("emails")

    with pytest.raises(
        QueueValidationError, match="Standard queues do not support message_group_id"
    ):
        queue._validate_message_options(
            delay_seconds=0,
            message_group_id="group",
            deduplication_id=None,
        )

    with pytest.raises(
        QueueValidationError, match="Standard queues do not support deduplication_id"
    ):
        queue._validate_message_options(
            delay_seconds=0,
            message_group_id=None,
            deduplication_id="dedup-1",
        )


def test_queue_copies_configured_tags() -> None:
    tags = {"team": "backend"}

    queue = SimpleQ().queue("emails", tags=tags)
    tags["team"] = "platform"

    assert queue.tags == {"team": "backend"}


@pytest.mark.parametrize(
    ("tags", "message"),
    [
        ({"": "value"}, "non-empty strings"),
        ({"aws:owner": "value"}, "must not start with 'aws:'"),
        ({"a" * 129: "value"}, "128 characters or fewer"),
        ({"owner": "v" * 257}, "256 characters or fewer"),
    ],
)
def test_queue_rejects_invalid_tags(tags: dict[str, str], message: str) -> None:
    with pytest.raises(QueueValidationError, match=message):
        SimpleQ().queue("emails", tags=tags)


def test_queue_rejects_more_than_fifty_tags() -> None:
    tags = {f"key-{index}": "value" for index in range(51)}

    with pytest.raises(QueueValidationError, match="at most 50"):
        SimpleQ().queue("emails", tags=tags)


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


def test_encode_message_attributes_allows_values_over_256_kib_up_to_1_mib() -> None:
    value = "a" * 300_000
    assert encode_message_attributes({"source": value}) == {
        "source": {"DataType": "String", "StringValue": value}
    }


def test_encode_message_attributes_rejects_values_larger_than_1_mib() -> None:
    with pytest.raises(QueueValidationError, match="at most 1048576 bytes"):
        encode_message_attributes({"source": "a" * (1_048_576 + 1)})


@pytest.mark.asyncio
async def test_enqueue_rejects_payloads_larger_than_1_mib() -> None:
    simpleq = SimpleQ()
    queue = simpleq.queue("emails")
    oversized_job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("a" * 1_100_000,),
        kwargs={},
        queue_name=queue.name,
    )

    with pytest.raises(QueueValidationError, match="at most 1048576 bytes"):
        await queue.enqueue(oversized_job)


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


@pytest.mark.asyncio
async def test_enqueue_many_rejects_batches_larger_than_1_mib() -> None:
    simpleq = SimpleQ()
    queue = simpleq.queue("emails")
    entries = [
        BatchEntry(
            job=Job(
                task_name="tests.fixtures.tasks:record_sync",
                args=("a" * 540_000,),
                kwargs={},
                queue_name=queue.name,
            )
        ),
        BatchEntry(
            job=Job(
                task_name="tests.fixtures.tasks:record_sync",
                args=("b" * 540_000,),
                kwargs={},
                queue_name=queue.name,
            )
        ),
    ]

    with pytest.raises(
        QueueValidationError,
        match="batch payloads must total at most 1048576 bytes",
    ):
        await queue.enqueue_many(entries)


@pytest.mark.asyncio
async def test_enqueue_rejects_fifo_routing_on_standard_queue() -> None:
    queue = SimpleQ().queue("emails")
    job = Job(
        task_name="tests.fixtures.tasks:record_sync",
        args=("hello",),
        kwargs={},
        queue_name=queue.name,
    )

    with pytest.raises(
        QueueValidationError, match="Standard queues do not support message_group_id"
    ):
        await queue.enqueue(job, message_group_id="group-1")

    with pytest.raises(
        QueueValidationError, match="Standard queues do not support deduplication_id"
    ):
        await queue.enqueue(job, deduplication_id="dedup-1")
