from cPickle import dumps

from boto.sqs import connect_to_region
from boto.sqs.message import Message


class Queue(object):
    """
    A representation of an Amazon SQS queue.

    There are two ways to create a Queue.

    1. Specify only a queue name, and connect to the default Amazon SQS region
       (us-east-1).  This will only work if you have your AWS credentials set
       appropriately in your environment (`AWS_ACCESS_KEY_ID` and
       `AWS_SECRET_ACCESS_KEY`).  For example::

       from sqsq.queues import Queue

       myqueue = Queue('myqueue')

    2. Specify a queue name, and a custom boto SQS connection.  For example:

       from boto.sqs import connect_to_region
       from sqsq.queues import Queue

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
        Initialize a new connection.

        :param str name: The name of the queue to use.
        :param obj connection: [optional] Either a
            boto.sqs.connection.SQSConnection object, or None.
        """
        self.name = name
        self._connection = connection or connect_to_region('us-east-1')
        self._queue = None

    @property
    def queue(self):
        """
        Handles lazy queue connections.

        If the specified queue doesn't exist, it will be created automatically.

        :returns: The SQS queue object.
        """
        if self._queue:
            return self._queue

        self._queue = self._connection.get_queue(self.name)
        if not self._queue:
            self._queue = self._connection.create_queue(self.name)

        return self._queue

    def delete(self):
        """Delete this SQS queue.

        This will remove all jobs in the queue, regardless of whether or not
        they're currently being processed.  This data cannot be recovered.
        """
        self._connection.delete_queue(self.queue)

    def enqueue(self, callable, *args, **kwargs):
        """
        Enqueue the specified callable, with the specified arguments.

        This will serialize the desired code, and dump it into the SQS queue.

        :param obj callable: A callable function, object, etc.
        :param list args: A list of callable arguments.
        :param dict kwargs: A dictionary of keyword arguments.
        """
        message = Message()
        message.set_body(dumps({
            'callable': callable,
            'args': args,
            'kwargs': kwargs,
        }))

        self.queue.write(message)

    @property
    def messages(self):
        """
        Return an iterator that allows the client to iterate through all
        existing messages in the cheapest, and quickest possible way.

        By default we will:

            - Use the maximum batch size to reduce calls to SQS.  This will
              reduce the cost of running the service, as less requests equals
              less dollars.

            - Wait for as long as possible (20 seconds) for a message to be
              sent to us (if none are in the queue already).  This way, we'll
              reduce our total request count, and spend less dollars.
        """
        return self.queue.get_messages(
            num_messages = self.BATCH_SIZE,
            wait_time_seconds = self.WAIT_SECONDS,
        )
