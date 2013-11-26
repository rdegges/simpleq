from time import sleep
from uuid import uuid4

from boto.sqs import connect_to_region
from boto.sqs.queue import Queue as SQSQueue
from sqsq.queues import Queue


def test_job(arg1=None, arg2=None):
    """This is a test job."""
    pass


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

    def test_enqueue(self):
        sid = uuid4().hex
        q = Queue(sid)

        q.enqueue(test_job, 'there')
        q.enqueue(test_job, arg1='test', arg2='test')
        sleep(10)

        assert len(q.messages) == 2
        q._connection.delete_queue(q.queue)
