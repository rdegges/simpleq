from cPickle import dumps
from datetime import datetime
from uuid import uuid4


class Job(object):
    """An abstraction for a single unit of work (a job!)."""

    def __init__(self, callable, *args, **kwargs):
        """Create a new Job,"""
        self.start_time = None
        self.stop_time = None
        self.run_time = None
        self._callable = callable
        self._args = args
        self._kwargs = kwargs
        self.exception = None
        self.result = None

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
