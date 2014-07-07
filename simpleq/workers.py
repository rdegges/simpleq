"""Our worker implementation."""


from gevent import monkey
monkey.patch_all()

from gevent.pool import Pool


class Worker(object):
    """
    A simple queue worker.

    This worker listens to one or more queues for jobs, then executes each job
    to complete the work.
    """
    def __init__(self, queues, concurrency=10):
        """
        Initialize a new worker.

        :param list queues: A list of queues to monitor.
        :param int concurrency: The amount of jobs to process concurrently.
            Depending on what type of concurrency is in use (*either gevent, or
            multiprocessing*), this may correlate to either green threads or CPU
            processes, respectively.
        """
        self.queues = queues
        self.concurrency = concurrency

    def __repr__(self):
        """Print a human-friendly object representation."""
        return '<Worker({"queues": %r})>' % self.queues

    def work(self, burst=False):
        """
        Monitor all queues and execute jobs.

        Once started, this will run forever (*unless the burst option is
        True*).

        :param bool burst: Should we quickly *burst* and finish all existing
            jobs then quit?
        """
        pool = Pool(self.concurrency)

        if burst:
            for queue in self.queues:
                for job in queue.jobs:
                    pool.spawn(job.run)
                    queue.remove_job(job)

            pool.join()
        else:
            while True:
                for queue in self.queues:
                    for job in self.queue.jobs:
                        pool.spawn(job.run)
                        queue.remove_job(job)

                pool.join()
