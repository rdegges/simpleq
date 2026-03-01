"""Test that all modules import correctly."""


def test_import_job():
    """Job class should import successfully."""
    from simpleq import Job
    assert Job is not None


def test_import_queue():
    """Queue class should import successfully."""
    from simpleq import Queue
    assert Queue is not None


def test_import_worker():
    """Worker class should import successfully."""
    from simpleq import Worker
    assert Worker is not None


def test_create_job():
    """Should be able to create a Job instance."""
    from simpleq import Job

    def sample_task(x, y):
        return x + y

    job = Job(sample_task, 1, 2)
    assert job.callable == sample_task
    assert job.args == (1, 2)
    assert job.kwargs == {}


def test_job_run():
    """Job should execute the callable."""
    from simpleq import Job

    results = []

    def sample_task(value):
        results.append(value)
        return value * 2

    job = Job(sample_task, 5)
    job.run()

    assert results == [5]
    assert job.result == 10
    assert job.exception is None
