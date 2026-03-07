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


def test_encode_message_attributes() -> None:
    assert encode_message_attributes({"source": "tests"}) == {
        "source": {"DataType": "String", "StringValue": "tests"}
    }


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
