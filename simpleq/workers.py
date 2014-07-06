"""Our worker implementation."""


from gevent.pool import Pool


class Worker(object):
    """
    A simple queue worker.

    This worker listens to one or more queues for jobs, then executes each job
    to complete the work.
    """
    def __init__(self, queues, concurrency):
        """
        Initialize a new worker.

        :param list queues: A list of queues to monitor.
        :param int concurrency: The amount of green threads to use whiile
            processing jobs.
        """
        self.queues = queues
        self.concurrency = concurrency

    def __repr__(self):
        """Print a human-friendly object representation."""
        return '<Worker({"queues": %r})>' % self.queues

    def work(self):
        """
        Monitor all queues and execute jobs.

        Once started, this will run forever.
        """
        pool = Pool(self.concurrency)
        while True:
            for queue in self.queues:
                for job in queue.jobs:
                    pool.spawn(job.run)

            pool.join()
