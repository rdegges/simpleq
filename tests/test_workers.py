"""All of our worker tests."""


from time import sleep
from unittest import TestCase
from uuid import uuid4

from simpleq.jobs import Job
from simpleq.queues import Queue
from simpleq.workers import Worker


def test_job(arg1=None, arg2=None):
    """This is a test job."""
    pass


class TestWorker(TestCase):

    def test_initialize(self):
        sid = uuid4().hex
        queue = Queue(sid)
        worker = Worker([queue])

        self.assertIsInstance(worker, Worker)

    def test_work(self):
        sid = uuid4().hex
        queue = Queue(sid)
        queue.add_job(Job(test_job, 'hi', 'there'))

        sleep(10)

        self.assertEqual(queue.num_jobs(), 1)

        worker = Worker([queue])
        worker.work(True)

        sleep(10)

        self.assertEqual(queue.num_jobs(), 0)
        queue.delete()
