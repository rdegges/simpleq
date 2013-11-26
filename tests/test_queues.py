from uuid import uuid4

from boto.sqs import connect_to_region
from boto.sqs.queue import Queue as SQSQueue
from sqsq.queues import Queue


class TestQueue:

    def test_lazy_create_queue(self):
        sid = uuid4().hex
        Queue(sid)

        assert not connect_to_region('us-east-1').get_queue(sid)

    def test_create_queue(self):
        sid = uuid4().hex
        q = Queue(sid)

        assert isinstance(q.queue, SQSQueue)
        q._connection.delete_queue(q.queue)
