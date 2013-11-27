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

    def work(self):
        """
        Monitor all queues and execute jobs.

        Once started, this will run forever.
        """
        while True:
            for queue in self.queues:
                for job in queue.jobs:
                    job.run()
