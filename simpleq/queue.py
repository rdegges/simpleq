"""Queue abstraction wrapping AWS SQS via boto3."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import boto3
import structlog

from simpleq.config import Config
from simpleq.cost import CostTracker
from simpleq.exceptions import (
    ConfigurationError,
    QueueError,
    QueueNotFoundError,
)
from simpleq.job import Job

if TYPE_CHECKING:
    from mypy_boto3_sqs.client import SQSClient

logger = structlog.get_logger()


class Queue:
    """A representation of an AWS SQS queue.

    Wraps boto3 SQS operations with cost tracking, auto-creation,
    and DLQ support.
    """

    def __init__(
        self,
        name: str,
        config: Config,
        cost_tracker: CostTracker | None = None,
        sqs_client: Any | None = None,
    ) -> None:
        self.name = name
        self.config = config
        self.cost_tracker = cost_tracker or CostTracker()
        self._client = sqs_client
        self._queue_url: str | None = None
        self._dlq_url: str | None = None

    def __repr__(self) -> str:
        return f'<Queue(name="{self.name}", region="{self.config.region}")>'

    @property
    def fifo(self) -> bool:
        return self.name.endswith(".fifo")

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                kwargs: dict[str, Any] = {"region_name": self.config.region}
                if self.config.endpoint_url:
                    kwargs["endpoint_url"] = self.config.endpoint_url
                self._client = boto3.client("sqs", **kwargs)
            except Exception as e:
                raise ConfigurationError(
                    "Failed to create SQS client. Check your AWS credentials.\n\n"
                    "  Set credentials using one of:\n"
                    "    export AWS_ACCESS_KEY_ID=xxx\n"
                    "    export AWS_SECRET_ACCESS_KEY=xxx\n\n"
                    "  Or configure the AWS CLI:\n"
                    "    aws configure\n\n"
                    f"  Error: {e}"
                ) from e
        return self._client

    @property
    def url(self) -> str:
        if self._queue_url is None:
            self._queue_url = self._get_or_create_url()
        return self._queue_url

    def _get_or_create_url(self) -> str:
        try:
            response = self.client.get_queue_url(QueueName=self.name)
            self.cost_tracker.track_other(self.name)
            return response["QueueUrl"]
        except self.client.exceptions.QueueDoesNotExist:
            if not self.config.auto_create:
                raise QueueNotFoundError(
                    f"Queue '{self.name}' does not exist.\n\n"
                    f"  Create it with: simpleq queue create {self.name}\n"
                    f"  Or set auto_create=True to create queues automatically."
                )
            logger.warning("queue_not_found_creating", queue_name=self.name)
            return self._create_queue()

    def _create_queue(self) -> str:
        attributes: dict[str, str] = {}

        if self.config.visibility_timeout != 30:
            attributes["VisibilityTimeout"] = str(self.config.visibility_timeout)

        if self.fifo:
            attributes["FifoQueue"] = "true"
            attributes["ContentBasedDeduplication"] = "true"

        kwargs: dict[str, Any] = {"QueueName": self.name}
        if attributes:
            kwargs["Attributes"] = attributes

        response = self.client.create_queue(**kwargs)
        self.cost_tracker.track_other(self.name)
        url = response["QueueUrl"]

        if self.config.dead_letter_queue:
            self._setup_dlq(url)

        return url

    def _setup_dlq(self, source_queue_url: str) -> None:
        dlq_name = (
            self.name.replace(".fifo", "-dlq.fifo")
            if self.fifo
            else f"{self.name}-dlq"
        )

        dlq_attrs: dict[str, str] = {}
        if self.fifo:
            dlq_attrs["FifoQueue"] = "true"
            dlq_attrs["ContentBasedDeduplication"] = "true"

        create_kwargs: dict[str, Any] = {"QueueName": dlq_name}
        if dlq_attrs:
            create_kwargs["Attributes"] = dlq_attrs

        dlq_response = self.client.create_queue(**create_kwargs)
        self._dlq_url = dlq_response["QueueUrl"]
        self.cost_tracker.track_other(self.name)

        dlq_arn_resp = self.client.get_queue_attributes(
            QueueUrl=self._dlq_url, AttributeNames=["QueueArn"]
        )
        dlq_arn = dlq_arn_resp["Attributes"]["QueueArn"]
        self.cost_tracker.track_other(self.name)

        redrive_policy = json.dumps(
            {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "5"}
        )
        self.client.set_queue_attributes(
            QueueUrl=source_queue_url,
            Attributes={"RedrivePolicy": redrive_policy},
        )
        self.cost_tracker.track_other(self.name)

    def send_job(
        self,
        job: Job,
        delay_seconds: int = 0,
        message_group_id: str | None = None,
        deduplication_id: str | None = None,
    ) -> None:
        """Send a job to this queue."""
        kwargs: dict[str, Any] = {
            "QueueUrl": self.url,
            "MessageBody": job.serialize(),
        }
        if delay_seconds:
            kwargs["DelaySeconds"] = delay_seconds
        if message_group_id and self.fifo:
            kwargs["MessageGroupId"] = message_group_id
        if deduplication_id and self.fifo:
            kwargs["MessageDeduplicationId"] = deduplication_id

        try:
            self.client.send_message(**kwargs)
        except Exception as e:
            if "NoCredential" in type(e).__name__ or "NoCredential" in str(e):
                raise ConfigurationError(
                    "AWS credentials not found.\n\n"
                    "  Set credentials using one of:\n"
                    "    export AWS_ACCESS_KEY_ID=xxx\n"
                    "    export AWS_SECRET_ACCESS_KEY=xxx\n\n"
                    "  Or configure the AWS CLI:\n"
                    "    aws configure"
                ) from e
            raise
        self.cost_tracker.track_send(self.name)

    def receive_jobs(self, max_messages: int | None = None) -> list[Job]:
        """Receive jobs from this queue via long polling."""
        response = self.client.receive_message(
            QueueUrl=self.url,
            MaxNumberOfMessages=max_messages or self.config.batch_size,
            WaitTimeSeconds=self.config.wait_seconds,
            AttributeNames=["ApproximateReceiveCount"],
        )
        self.cost_tracker.track_receive(self.name)

        messages = response.get("Messages", [])
        jobs = []
        for msg in messages:
            receive_count = int(
                msg.get("Attributes", {}).get("ApproximateReceiveCount", "1")
            )
            job = Job.deserialize(
                msg["Body"],
                receipt_handle=msg["ReceiptHandle"],
                message_id=msg["MessageId"],
                receive_count=receive_count,
            )
            jobs.append(job)

        return jobs

    def delete_job(self, job: Job) -> None:
        """Delete a processed job from the queue."""
        if job.receipt_handle is None:
            raise QueueError("Cannot delete job without a receipt handle.")

        self.client.delete_message(
            QueueUrl=self.url,
            ReceiptHandle=job.receipt_handle,
        )
        self.cost_tracker.track_delete(self.name)

    def change_visibility(self, job: Job, timeout: int) -> None:
        """Change the visibility timeout of a job (used for retry backoff)."""
        if job.receipt_handle is None:
            raise QueueError(
                "Cannot change visibility without a receipt handle."
            )

        self.client.change_message_visibility(
            QueueUrl=self.url,
            ReceiptHandle=job.receipt_handle,
            VisibilityTimeout=timeout,
        )
        self.cost_tracker.track_other(self.name)

    def num_jobs(self) -> int:
        """Return the approximate number of messages in this queue."""
        response = self.client.get_queue_attributes(
            QueueUrl=self.url,
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        self.cost_tracker.track_other(self.name)
        return int(response["Attributes"]["ApproximateNumberOfMessages"])

    def purge(self) -> None:
        """Delete all messages in this queue."""
        self.client.purge_queue(QueueUrl=self.url)
        self.cost_tracker.track_other(self.name)

    def delete(self) -> None:
        """Delete this queue entirely."""
        self.client.delete_queue(QueueUrl=self.url)
        self.cost_tracker.track_other(self.name)
        self._queue_url = None

    def get_dlq_jobs(self) -> list[Job]:
        """Read messages from this queue's dead letter queue."""
        dlq_name = (
            self.name.replace(".fifo", "-dlq.fifo")
            if self.fifo
            else f"{self.name}-dlq"
        )

        try:
            resp = self.client.get_queue_url(QueueName=dlq_name)
        except self.client.exceptions.QueueDoesNotExist:
            raise QueueNotFoundError(
                f"No DLQ configured for queue '{self.name}'.\n\n"
                f"  Create one with: SimpleQ(dead_letter_queue=True)"
            )

        dlq_url = resp["QueueUrl"]
        response = self.client.receive_message(
            QueueUrl=dlq_url,
            MaxNumberOfMessages=self.config.batch_size,
            WaitTimeSeconds=0,
        )
        self.cost_tracker.track_receive(dlq_name)

        messages = response.get("Messages", [])
        return [
            Job.deserialize(
                msg["Body"],
                receipt_handle=msg["ReceiptHandle"],
                message_id=msg["MessageId"],
            )
            for msg in messages
        ]

    def redrive_dlq(self) -> int:
        """Move all messages from the DLQ back to this queue.

        Returns the number of messages redriven.
        """
        count = 0
        while True:
            jobs = self.get_dlq_jobs()
            if not jobs:
                break

            dlq_name = (
                self.name.replace(".fifo", "-dlq.fifo")
                if self.fifo
                else f"{self.name}-dlq"
            )
            dlq_url = self.client.get_queue_url(QueueName=dlq_name)[
                "QueueUrl"
            ]

            for job in jobs:
                self.send_job(job)
                if job.receipt_handle:
                    self.client.delete_message(
                        QueueUrl=dlq_url,
                        ReceiptHandle=job.receipt_handle,
                    )
                count += 1

        return count
