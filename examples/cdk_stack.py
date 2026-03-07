"""AWS CDK example that provisions queues for a SimpleQ app."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aws_cdk import Duration, Stack
from aws_cdk import aws_sqs as sqs

if TYPE_CHECKING:
    from constructs import Construct


class SimpleQStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        dlq = sqs.Queue(
            self,
            "EmailsDlq",
            retention_period=Duration.days(14),
        )

        sqs.Queue(
            self,
            "EmailsQueue",
            visibility_timeout=Duration.seconds(300),
            receive_message_wait_time=Duration.seconds(20),
            dead_letter_queue=sqs.DeadLetterQueue(
                queue=dlq,
                max_receive_count=3,
            ),
        )
