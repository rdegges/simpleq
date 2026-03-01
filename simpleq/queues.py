"""This module holds our queue abstractions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

import boto3

if TYPE_CHECKING:
    from mypy_boto3_sqs.service_resource import Queue as SQSQueue

from simpleq.jobs import Job


class Queue:
    """A representation of an Amazon SQS queue.

    There are two ways to create a Queue:

    1. Specify only a queue name, and connect to the default Amazon SQS region
       (us-east-1). This will only work if you have your AWS credentials set
       appropriately in your environment (AWS_ACCESS_KEY_ID and
       AWS_SECRET_ACCESS_KEY). To set your environment variables, you can
       use the shell command export::

            $ export AWS_ACCESS_KEY_ID=xxx
            $ export AWS_SECRET_ACCESS_KEY=xxx

       You can then create a queue as follows::

            from simpleq.queues import Queue

            myqueue = Queue('myqueue')

    2. Specify a queue name and a custom region. For example::

            from simpleq.queues import Queue

            myqueue = Queue('myqueue', region='us-west-1')
    """

    BATCH_SIZE = 10
    WAIT_SECONDS = 20

    def __init__(self, name: str, region: str = 'us-east-1') -> None:
        """Initialize an SQS queue.

        This will create a new boto3 SQS connection in the background, which will
        be used for all future queue requests. This will speed up communication
        with SQS by taking advantage of boto3's connection pooling functionality.

        Args:
            name: The name of the queue to use.
            region: The AWS region (default: us-east-1).
        """
        self.name = name
        self.region = region
        self.sqs = boto3.resource('sqs', region_name=region)
        self._queue: SQSQueue | None = None

    def __repr__(self) -> str:
        """Print a human-friendly object representation."""
        return f'<Queue({{"name": "{self.name}", "region": "{self.region}"}}))>'

    @property
    def queue(self) -> SQSQueue:
        """Return the underlying SQS queue object from boto3.

        This will either lazily create (or retrieve) the queue from SQS by name.

        Returns:
            The SQS queue object.
        """
        if self._queue:
            return self._queue

        try:
            self._queue = self.sqs.get_queue_by_name(QueueName=self.name)
        except self.sqs.meta.client.exceptions.QueueDoesNotExist:
            self._queue = self.sqs.create_queue(QueueName=self.name)

        return self._queue

    def num_jobs(self) -> int:
        """Return the number of jobs currently in this SQS queue.

        Returns:
            The number of jobs currently in this SQS queue.
        """
        attributes = self.queue.attributes
        return int(attributes.get('ApproximateNumberOfMessages', 0))

    def delete(self) -> None:
        """Delete this SQS queue.

        This will remove all jobs in the queue, regardless of whether or not
        they're currently being processed. This data cannot be recovered.
        """
        self.queue.delete()

    def add_job(self, job: Job) -> None:
        """Add a new job to the queue.

        This will serialize the desired code, and dump it into this SQS queue
        to be processed.

        Args:
            job: The Job to enqueue.
        """
        self.queue.send_message(MessageBody=job.message_body.decode())

    def remove_job(self, message) -> None:
        """Remove a job from the queue.

        Args:
            message: The SQS message to delete.
        """
        message.delete()

    @property
    def jobs(self) -> Iterator[tuple[Job, Any]]:
        """Iterate through all existing jobs in the cheapest and quickest possible way.

        By default we will:

            - Use the maximum batch size to reduce calls to SQS. This will
              reduce the cost of running the service, as fewer requests equals
              fewer dollars.

            - Wait for as long as possible (20 seconds) for a message to be
              sent to us (if none are in the queue already). This way, we'll
              reduce our total request count, and spend fewer dollars.

        Note:
            This method is a generator which will continue to return results
            until this SQS queue is emptied.

        Yields:
            Tuple of (Job, message) where message is needed for deletion.
        """
        total_jobs = self.num_jobs()

        while total_jobs:
            messages = self.queue.receive_messages(
                MaxNumberOfMessages=self.BATCH_SIZE,
                WaitTimeSeconds=self.WAIT_SECONDS,
            )

            for message in messages:
                job = Job.from_message(message.body)
                yield job, message

            total_jobs = self.num_jobs()
