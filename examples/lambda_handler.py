"""AWS Lambda example for SimpleQ producers."""

from __future__ import annotations

from simpleq import SimpleQ

sq = SimpleQ()
queue = sq.queue("events", dlq=True)


@sq.task(queue=queue)
def process_event(event_name: str, detail: dict[str, object]) -> None:
    print(event_name, detail)


def handler(event: dict[str, object], context: object) -> dict[str, str]:
    del context
    process_event.delay_sync("lambda-event", event)
    return {"status": "queued"}
