"""Job model — a single unit of work to be processed by a worker."""

from __future__ import annotations

import base64
import pickle
from dataclasses import dataclass, field
from datetime import datetime, timezone

from simpleq.exceptions import MessageTooLargeError, SerializationError

SQS_MAX_MESSAGE_SIZE = 262_144  # 256KB


@dataclass
class Job:
    """Represents a serializable unit of work sent to SQS."""

    task_name: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    id: str | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    receipt_handle: str | None = None
    receive_count: int = 0

    def serialize(self) -> str:
        """Serialize this job to a base64-encoded pickle string for SQS."""
        try:
            data = pickle.dumps(
                {
                    "task_name": self.task_name,
                    "args": self.args,
                    "kwargs": self.kwargs,
                    "created_at": self.created_at.isoformat(),
                }
            )
        except (pickle.PicklingError, TypeError) as e:
            raise SerializationError(
                f"Failed to serialize task '{self.task_name}' arguments. "
                f"Ensure all arguments are picklable.\n\n  Error: {e}"
            ) from e

        encoded = base64.b64encode(data).decode("utf-8")

        if len(encoded) > SQS_MAX_MESSAGE_SIZE:
            raise MessageTooLargeError(
                f"Serialized payload for task '{self.task_name}' is "
                f"{len(encoded):,} bytes, which exceeds the SQS limit of "
                f"{SQS_MAX_MESSAGE_SIZE:,} bytes (256KB).\n\n"
                f"  Consider passing smaller arguments or storing large data "
                f"in S3."
            )

        return encoded

    @classmethod
    def deserialize(
        cls,
        body: str,
        receipt_handle: str | None = None,
        message_id: str | None = None,
        receive_count: int = 0,
    ) -> Job:
        """Deserialize a job from an SQS message body.

        Security: Uses pickle deserialization, which can execute arbitrary
        code. Only process messages from SQS queues you control. Do not
        expose queue write access to untrusted sources.
        """
        try:
            data = pickle.loads(base64.b64decode(body))  # noqa: S301
        except Exception as e:
            raise SerializationError(
                f"Failed to deserialize job message.\n\n  Error: {e}"
            ) from e

        return cls(
            task_name=data["task_name"],
            args=tuple(data.get("args", ())),
            kwargs=data.get("kwargs", {}),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if "created_at" in data
                else datetime.now(timezone.utc)
            ),
            receipt_handle=receipt_handle,
            id=message_id,
            receive_count=receive_count,
        )
