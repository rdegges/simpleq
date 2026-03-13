"""Shared transport contract scenarios for LocalStack and InMemoryTransport."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from simpleq.job import Job

if TYPE_CHECKING:
    from simpleq import SimpleQ

_TASK_NAME = "tests.fixtures.tasks:record_sync"


def _fifo_queue_name(base_name: str) -> str:
    normalized = base_name.removesuffix(".fifo")
    return f"{normalized[:75]}.fifo"


async def transport_contract_summary(
    simpleq: SimpleQ,
    *,
    base_name: str,
    cleanup_queues: list[object] | None = None,
    include_receive_attempt_replay: bool = True,
) -> dict[str, object]:
    """Run the supported transport contract scenarios and return a summary."""
    fifo_queue = simpleq.queue(
        _fifo_queue_name(f"{base_name}-fifo"),
        fifo=True,
        content_based_deduplication=False,
        wait_seconds=0,
        visibility_timeout=2,
    )
    standard_queue = simpleq.queue(
        f"{base_name}-standard",
        wait_seconds=0,
        visibility_timeout=2,
    )
    if cleanup_queues is not None:
        cleanup_queues.extend([standard_queue, fifo_queue])

    first_job = Job(
        task_name=_TASK_NAME,
        args=("first",),
        kwargs={},
        queue_name=fifo_queue.name,
    )
    second_job = Job(
        task_name=_TASK_NAME,
        args=("second",),
        kwargs={},
        queue_name=fifo_queue.name,
    )
    await fifo_queue.enqueue(
        first_job,
        message_group_id="group-1",
        deduplication_id="dedup-first",
    )
    await fifo_queue.enqueue(
        second_job,
        message_group_id="group-1",
        deduplication_id="dedup-second",
    )

    first_receive_kwargs: dict[str, object] = {
        "max_messages": 1,
        "wait_seconds": 0,
    }
    if include_receive_attempt_replay:
        first_receive_kwargs["receive_request_attempt_id"] = "attempt-1"
    first_receive = await fifo_queue.receive(**first_receive_kwargs)
    summary: dict[str, object] = {
        "first_value": first_receive[0].args[0],
    }
    if include_receive_attempt_replay:
        replay_receive = await fifo_queue.receive(
            max_messages=1,
            wait_seconds=0,
            receive_request_attempt_id="attempt-1",
        )
        summary.update(
            {
                "replay_same_job_id": first_receive[0].job_id
                == replay_receive[0].job_id,
                "replay_same_receipt_handle": (
                    first_receive[0].receipt_handle == replay_receive[0].receipt_handle
                ),
            }
        )
    blocked_receive = await fifo_queue.receive(max_messages=1, wait_seconds=0)
    await fifo_queue.ack(first_receive[0])
    second_receive = await fifo_queue.receive(max_messages=1, wait_seconds=0)
    await fifo_queue.ack(second_receive[0])

    dedup_job = Job(
        task_name=_TASK_NAME,
        args=("dedup",),
        kwargs={},
        queue_name=fifo_queue.name,
    )
    first_dedup_id = await fifo_queue.enqueue(
        dedup_job,
        message_group_id="group-2",
        deduplication_id="dedup-shared",
    )
    second_dedup_id = await fifo_queue.enqueue(
        dedup_job,
        message_group_id="group-2",
        deduplication_id="dedup-shared",
    )
    dedup_receive = await fifo_queue.receive(max_messages=5, wait_seconds=0)
    for job in dedup_receive:
        await fifo_queue.ack(job)

    delayed_job = Job(
        task_name=_TASK_NAME,
        args=("delayed",),
        kwargs={},
        queue_name=standard_queue.name,
    )
    await standard_queue.enqueue(delayed_job, delay_seconds=1)
    start = time.monotonic()
    delayed_receive = await standard_queue.receive(max_messages=1, wait_seconds=2)
    delayed_elapsed = time.monotonic() - start
    await standard_queue.ack(delayed_receive[0])

    summary.update(
        {
            "blocked_receive_empty": blocked_receive == [],
            "second_value": second_receive[0].args[0],
            "deduplication_reused_message_id": first_dedup_id == second_dedup_id,
            "deduplication_receive_count": len(dedup_receive),
            "delayed_value": delayed_receive[0].args[0],
            "delayed_long_poll_waited": delayed_elapsed >= 0.8,
        }
    )
    return summary
