# SimpleQ

A simple, infinitely scalable, SQS based queue.

[![Build Status](https://travis-ci.org/rdegges/simpleq.svg?branch=master)](https://travis-ci.org/rdegges/simpleq)

![SimpleQ Logo](https://github.com/rdegges/simpleq/raw/master/assets/happy-snake.jpg)


## Meta

- Author: Randall Degges
- Email: r@rdegges.com
- Site: http://www.rdegges.com
- Status: in-development, active


## Purpose

As I've been developing large scale web applications in Python for several
years, I've come to try all of the available queueing solutions, namely
[Celery][] and [RQ][].

What I love about Celery is that it supports many backends, and is extremely
configurable.  Celery is great for large projects where you need to support very
specific queueing requirements, and have lots of time to spend configuring and
optimizing your software.

On the other end of the spectrum is RQ -- RQ is a very simple, minimalistic,
queueing system which exclusively works with [Redis][].  I love RQ because it
can be dropped into any Python project in a number of minutes, and requires very
little configuration.  It also ships with a great dashboard and utilities.

**Now the downsides.**

As I've built more and more software over the years, I've come to really
appreciate [Amazon SQS][] (*Simple Queue Service*).  Not only is it incredibly
fast and available in all of the [AWS Regions][], but it's the cheapest possible
queueing system (*in terms of hosting costs*) by a huge margin, it requires 0
setup and configuration (*other than having an AWS account*), and almost never
goes down.

What I really want to use is a simple queue system like RQ, that exclusively
runs on SQS and is optimized for speed and cost.  This means a queue system that
will properly handle batching messages (*my main issue with Celery is that it
does not support this*) and require minimal configuration.

My goal with SimpleQ is to build the queueing system I've always wanted: a
simple SQS based queue that is extremely stable, fast, and cost effective.


## Documentation

This project's documentation is hosted at ReadTheDocs, for all usage and setup
information you'll want to follow this link:
http://simpleq.readthedocs.org/en/latest


-Randall


  [Celery]: http://www.celeryproject.org/ "Celery Task Queue"
  [RQ]: http://python-rq.org/ "Python RQ"
  [Redis]: http://redis.io/ "Redis"
  [Amazon SQS]: http://aws.amazon.com/sqs/ "SQS"
  [AWS Regions]: http://docs.aws.amazon.com/general/latest/gr/rande.html#sqs_region "AWS SQS Regions"
