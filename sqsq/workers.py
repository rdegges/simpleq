from gevent.pool import Pool


class Worker(object):
    """
    A simple queue worker.

    This worker listens to one or more queues for jobs, then executes each job
    to complete the work.
    """
    def __init__(self, queues):
        """
        Initialize a new worker.

        :param list queues: A list of queues to monitor.
        """
        self.queues = queues

    def __repr__(self):
        """Print a human-friendly object representation."""
        return '<Worker({"queues": %r})>' % self.queues

    def work(self):
        """
        Monitor all queues and execute jobs.

        Once started, this will run forever.
        """
        pool = Pool(1000)
        while True:
            for queue in self.queues:
                for job in queue.jobs:
                    pool.spawn(job.run)

            pool.join()
