"""Django integration example for SimpleQ."""

from __future__ import annotations

from simpleq import SimpleQ

sq = SimpleQ()
queue = sq.queue("emails", dlq=True)


@sq.task(queue=queue)
def send_welcome_email(user_id: int) -> None:
    print(f"send welcome email to user={user_id}")


def enqueue_signup_email(user_id: int) -> None:
    send_welcome_email.delay_sync(user_id)


def run_worker() -> None:
    sq.worker(queues=[queue], concurrency=2).work_sync()
