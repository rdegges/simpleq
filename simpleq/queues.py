"""This module holds our queue abstractions."""


from boto.sqs import connect_to_region

from simpleq.jobs import Job


class Queue(object):
    """
    A representation of an Amazon SQS queue.

    There are two ways to create a Queue.

    1. Specify only a queue name, and connect to the default Amazon SQS region
       (*us-east-1*).  This will only work if you have your AWS credentials set
       appropriately in your environment (*``AWS_ACCESS_KEY_ID`` and
       ``AWS_SECRET_ACCESS_KEY``*).  To set your environment variables, you can
       use the shell command ``export``::

            $ export AWS_ACCESS_KEY_ID=xxx
            $ export AWS_SECRET_ACCESS_KEY=xxx

       You can then create a queue as follows::

            from simpleq.queues import Queue

            myqueue = Queue('myqueue')

    2. Specify a queue name, and a custom boto SQS connection.  For example::

            from boto.sqs import connect_to_region
            from simpleq.queues import Queue

            myqueue = Queue(
                'myqueue',
                connection = connect_to_region(
                    'us-west-1',
                    aws_access_key_id = 'blah',
                    aws_secret_access_key = 'blah'
                )
            )
    """
    BATCH_SIZE = 10
    WAIT_SECONDS = 20

    def __init__(self, name, connection=None):
        """
        Initialize an SQS queue.

        This will create a new boto SQS connection in the background, which will
        be used for all future queue requests.  This will speed up communication
        with SQS by taking advantage of boto's connection pooling functionality.

        :param str name: The name of the queue to use.
        :param obj connection: [optional] Either a boto connection object, or None.
        """
        self.name = name
        self.connection = connection or connect_to_region('us-east-1')
        self._queue = None

    def __repr__(self):
        """Print a human-friendly object representation."""
        return '<Queue({"name": "%s", "region": "%s"})>' % (
            self.name,
            self.connection.region.name,
        )

    @property
    def queue(self):
        """
        Return the underlying SQS queue object from boto.

        This will either lazily create (*or retrieve*) the queue from SQS by
        name.

        :returns: The SQS queue object.
        """
        if self._queue:
            return self._queue

        self._queue = self.connection.get_queue(self.name)
        if not self._queue:
            self._queue = self.connection.create_queue(self.name)

        return self._queue

    def num_jobs(self):
        """
        Return the amount of jobs currently in this SQS queue.

        :rtype: int
        :returns: The amount of jobs currently in this SQS queue.
        """
        return self.queue.count()

    def delete(self):
        """
        Delete this SQS queue.

        This will remove all jobs in the queue, regardless of whether or not
        they're currently being processed.  This data cannot be recovered.
        """
        self.connection.delete_queue(self.queue)

    def add_job(self, job):
        """
        Add a new job to the queue.

        This will serialize the desired code, and dump it into this SQS queue
        to be processed.

        :param obj job: The Job to enqueue.
        """
        self.queue.write(job.message)

    def remove_job(self, job):
        """
        Remove a job from the queue.

        :param obj job: The Job to dequeue.
        """
        self.queue.delete_message(job.message)

    @property
    def jobs(self):
        """
        Iterate through all existing jobs in the cheapest and quickest possible
        way.

        By default we will:

            - Use the maximum batch size to reduce calls to SQS.  This will
              reduce the cost of running the service, as less requests equals
              less dollars.

            - Wait for as long as possible (*20 seconds*) for a message to be
              sent to us (*if none are in the queue already*).  This way, we'll
              reduce our total request count, and spend less dollars.

        .. note::
            This method is a generator which will continue to return results
            until this SQS queue is emptied.
        """
        total_jobs = self.num_jobs()

        while total_jobs:
            for message in self.queue.get_messages(
                num_messages = self.BATCH_SIZE,
                wait_time_seconds = self.WAIT_SECONDS,
            ):
                yield Job.from_message(message)

            total_jobs = self.num_jobs()
