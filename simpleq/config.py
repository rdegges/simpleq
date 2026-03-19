"""SimpleQ configuration with sensible defaults and environment auto-detection."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Config:
    """Configuration for a SimpleQ instance.

    Supports overrides via constructor arguments and environment variables.
    Environment variables are only used as fallbacks when no explicit value
    is provided.
    """

    region: str = "us-east-1"
    endpoint_url: str | None = None
    dead_letter_queue: bool = False
    visibility_timeout: int = 30
    auto_create: bool = True
    batch_size: int = 10
    wait_seconds: int = 20

    def __post_init__(self) -> None:
        if self.endpoint_url is None:
            self.endpoint_url = os.getenv("SIMPLEQ_ENDPOINT_URL")

        env_region = os.getenv("AWS_DEFAULT_REGION")
        if env_region and self.region == "us-east-1":
            self.region = env_region
