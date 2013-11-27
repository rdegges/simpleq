from time import sleep

from sqsq.jobs import Job


def random_job(arg1=None, arg2=None):
    """A sample job for testing."""
    sleep(1)
    return 'yo!'


def bad_job():
    return 1 / 0


class TestJob:

    def test_create_job(self):
        job = Job(random_job, 'hi', arg2='there')
        assert isinstance(job, Job)

    def test_run(self):
        job = Job(random_job, 'hi', arg2='there')
        job.run()

        assert job.run_time >= 1
        assert job.result == 'yo!'

        job = Job(bad_job)
        job.run()

        assert isinstance(job.exception, ZeroDivisionError)

    def test_serialize(self):
        job = Job(random_job)
        assert isinstance(job.serialize(), str)
