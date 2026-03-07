"""Manual benchmark helpers for SimpleQ."""

from __future__ import annotations

import asyncio
import json
import os
import time
from uuid import uuid4

import boto3

from simpleq import SimpleQ
from simpleq.config import detect_localstack_endpoint
from tests.fixtures import tasks


async def run_benchmark(job_count: int = 1_000) -> dict[str, float]:
    """Enqueue and process a configurable number of jobs."""
    endpoint_url = (
        os.getenv("SIMPLEQ_ENDPOINT_URL")
        or detect_localstack_endpoint()
        or "http://localhost:4566"
    )
    simpleq = SimpleQ(
        endpoint_url=endpoint_url,
        wait_seconds=0,
        visibility_timeout=2,
    )
    queue = simpleq.queue(f"benchmark-{uuid4().hex[:8]}", wait_seconds=0)
    task = simpleq.task(queue=queue)(tasks.record_async)

    started = time.perf_counter()
    for index in range(job_count):
        await task.delay(f"job-{index}")
    enqueue_seconds = time.perf_counter() - started

    worker = simpleq.worker(queues=[queue], concurrency=10, poll_interval=0.0)
    started = time.perf_counter()
    await worker.work(burst=True)
    process_seconds = time.perf_counter() - started
    await asyncio.sleep(0)
    await queue.delete()

    return {
        "job_count": float(job_count),
        "enqueue_seconds": enqueue_seconds,
        "process_seconds": process_seconds,
        "jobs_per_second": job_count / max(process_seconds, 0.001),
        "requests_per_job": simpleq.cost_tracker.metrics_for(queue.name).total_requests
        / job_count,
    }


def run_raw_sqs_benchmark(job_count: int = 1_000) -> dict[str, float]:
    """Benchmark a direct boto3 SQS loop against LocalStack or AWS."""
    endpoint_url = os.getenv("SIMPLEQ_ENDPOINT_URL", "http://localhost:4566")
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    client = boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "test"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "test"),
    )
    queue_name = f"raw-benchmark-{uuid4().hex[:8]}"
    queue_url = client.create_queue(QueueName=queue_name)["QueueUrl"]

    started = time.perf_counter()
    for index in range(job_count):
        client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"job": index}),
        )
    enqueue_seconds = time.perf_counter() - started

    processed = 0
    started = time.perf_counter()
    while processed < job_count:
        response = client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=0,
            AttributeNames=["All"],
        )
        messages = response.get("Messages", [])
        if not messages:
            continue
        for message in messages:
            client.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=message["ReceiptHandle"],
            )
            processed += 1
    process_seconds = time.perf_counter() - started
    client.delete_queue(QueueUrl=queue_url)

    return {
        "job_count": float(job_count),
        "enqueue_seconds": enqueue_seconds,
        "process_seconds": process_seconds,
        "jobs_per_second": job_count / max(process_seconds, 0.001),
    }


async def compare_simpleq_to_raw_sqs(job_count: int = 1_000) -> dict[str, float]:
    """Return a side-by-side throughput snapshot for SimpleQ and raw SQS."""
    simpleq_metrics = await run_benchmark(job_count)
    raw_metrics = await asyncio.to_thread(run_raw_sqs_benchmark, job_count)
    return {
        "simpleq_jobs_per_second": simpleq_metrics["jobs_per_second"],
        "raw_sqs_jobs_per_second": raw_metrics["jobs_per_second"],
        "simpleq_requests_per_job": simpleq_metrics["requests_per_job"],
    }
