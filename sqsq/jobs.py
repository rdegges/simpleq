from cPickle import dumps, loads
from datetime import datetime
from uuid import uuid4

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
        self._callable = callable
        self._args = args
        self._kwargs = kwargs
        self._message = Message(body=dumps({
            'callable': self._callable,
            'args': self._args,
            'kwargs': self._kwargs,
        }))

    @classmethod
    def from_message(cls, message):
        """
        Create a new Job, given a boto Message.

        :param obj message: The boto Message object to use.
        """
        data = loads(message.get_body())
        job = cls(data['callable'], *data['args'], **data['kwargs'])
        job._message = message

        return job

    def run(self):
        """Run this job."""
        self.start_time = datetime.utcnow()
        jid = uuid4().hex

        print 'Starting job:', jid, 'at:', self.start_time.isoformat()

        try:
            self.result = self._callable(*self._args, **self._kwargs)
        except Exception, e:
            self.exception = e

        self.stop_time = datetime.utcnow()
        self.run_time = (self.stop_time - self.start_time).total_seconds()
        print 'Finished job:', jid, 'at:', self.stop_time.isoformat(), 'in:', self.run_time, 'seconds'
