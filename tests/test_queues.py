"""All of our queue tests."""


from time import sleep
from unittest import TestCase
from uuid import uuid4

from boto.sqs import connect_to_region
from boto.sqs.queue import Queue as SQSQueue

from simpleq.jobs import Job
from simpleq.queues import Queue


def test_job(arg1=None, arg2=None):
    """This is a test job."""
    pass


class TestQueue(TestCase):

    def test_lazy_create_queue(self):
        sid = uuid4().hex
        Queue(sid)

        self.assertNotTrue(connect_to_region('us-east-1').get_queue(sid))

    def test_create_queue(self):
        sid = uuid4().hex
        q = Queue(sid)

        self.assertIsInstance(q.queue, SQSQueue)
        q.delete()

    def test_delete_queue(self):
        sid = uuid4().hex
        q = Queue(sid)

        self.assertIsInstance(q.queue, SQSQueue)
        q.delete()

        assert not connect_to_region('us-east-1').get_queue(sid)

    def test_add_job(self):
        sid = uuid4().hex
        q = Queue(sid)

        q.add_job(Job(test_job, 'there'))
        q.add_job(Job(test_job, arg1='test', arg2='test'))
        sleep(10)

        self.assertEqual(len(q.jobs), 2)
        q.delete()

    def test_remove_job(self):
        sid = uuid4().hex
        q = Queue(sid)

        q.add_job(Job(test_job, 'there'))
        q.add_job(Job(test_job, arg1='test', arg2='test'))
        sleep(10)

        for job in q.jobs:
            q.remove_job(job)

        sleep(10)

        self.assertEqual(len(q.jobs), 0)
        q.delete()
