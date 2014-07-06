from pickle import dumps, loads
from datetime import datetime

from boto.sqs.message import Message


class Job(object):
    """An abstraction for a single unit of work (a job!)."""

    def __init__(self, callable, *args, **kwargs):
        """
        Create a new Job,

        :param obj callable: [optional] A callable to run.
        """
        self.start_time = None
        self.stop_time = None
        self.run_time = None
        self.exception = None
        self.result = None
        self.callable = callable
        self.args = args
        self.kwargs = kwargs
        self.message = Message(body=dumps({
            'callable': self.callable,
            'args': self.args,
            'kwargs': self.kwargs,
        }))

    def __repr__(self):
        """Print a human-friendly object representation."""
        return '<Job({"callable": "%s"})>' % (
            self.callable.__name__,
        )

    @classmethod
    def frommessage(cls, message):
        """
        Create a new Job, given a boto Message.

        :param obj message: The boto Message object to use.
        """
        data = loads(message.get_body())
        job = cls(data['callable'], *data['args'], **data['kwargs'])
        job.message = message

        return job

    def log(self, message):
        """
        Write the given message to standard out (STDOUT).
        """
        print 'sqsq: %s' % message

    def run(self):
        """Run this job."""
        self.start_time = datetime.utcnow()
        self.log('Starting job %s at %s.' % (
            self.callable.__name__,
            self.start_time.isoformat(),
        ))

        try:
            self.result = self.callable(*self.args, **self.kwargs)
        except Exception, e:
            self.exception = e

        self.stop_time = datetime.utcnow()
        self.run_time = (self.stop_time - self.start_time).total_seconds()
        self.log('Finished job %s at %s in %s seconds.' % (
            self.callable.__name__,
            self.stop_time.isoformat(),
            self.run_time,
        ))
