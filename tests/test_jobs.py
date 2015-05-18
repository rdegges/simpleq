"""All of our job tests."""


from pickle import dumps
from time import sleep
from unittest import TestCase

from boto.sqs.message import Message

from simpleq.jobs import Job


def random_job(arg1=None, arg2=None):
    """A sample job for testing."""
    sleep(1)
    return 'yo!'


def bad_job():
    return 1 / 0


class TestJob(TestCase):

    def test_create_job(self):
        job = Job(random_job, 'hi', arg2='there')
        self.assertIsInstance(job, Job)

    def test_create_job_from_message(self):
        message = Message(body=dumps({
            'callable': random_job,
            'args': (),
            'kwargs': {},
        }))

        job = Job.from_message(message)
        self.assertEqual(message.get_body(), job.message.get_body())

    def test_run(self):
        job = Job(random_job, 'hi', arg2='there')
        job.run()

        self.assertTrue(job.run_time >= 1)
        self.assertEqual(job.result, 'yo!')

        job = Job(bad_job)
        job.run()

        self.assertIsInstance(job.exception, ZeroDivisionError)
