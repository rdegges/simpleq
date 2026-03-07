"""FastAPI integration example for SimpleQ."""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from simpleq import SimpleQ

app = FastAPI()
sq = SimpleQ()
queue = sq.queue("emails", dlq=True)


class EmailPayload(BaseModel):
    to: str
    subject: str
    body: str


@sq.task(queue=queue, schema=EmailPayload)
async def send_email(payload: EmailPayload) -> None:
    print(f"sent {payload.subject} to {payload.to}")


@app.post("/emails")
async def enqueue_email(payload: EmailPayload) -> dict[str, str]:
    job = await send_email.delay(payload)
    return {"job_id": job.job_id}
