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
        assert isinstance(job, Job)

    def test_create_job_from_message(self):
        message = Message(body=dumps({
            'callable': random_job,
            'args': (),
            'kwargs': {},
        }))

        job = Job.from_message(message)
        assert message == job._message

    def test_run(self):
        job = Job(random_job, 'hi', arg2='there')
        job.run()

        assert job.run_time >= 1
        assert job.result == 'yo!'

        job = Job(bad_job)
        job.run()

        assert isinstance(job.exception, ZeroDivisionError)
