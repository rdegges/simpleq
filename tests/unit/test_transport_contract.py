"""Unit-level contract tests for InMemoryTransport."""

from __future__ import annotations

import pytest

from simpleq import SimpleQ
from simpleq.testing import InMemoryTransport
from tests.fixtures.transport_contract import transport_contract_summary


@pytest.mark.asyncio
async def test_inmemory_transport_contract_summary() -> None:
    summary = await transport_contract_summary(
        SimpleQ(transport=InMemoryTransport()),
        base_name="unit-contract",
    )

    assert summary == {
        "first_value": "first",
        "replay_same_job_id": True,
        "replay_same_receipt_handle": True,
        "blocked_receive_empty": True,
        "second_value": "second",
        "deduplication_reused_message_id": True,
        "deduplication_receive_count": 1,
        "delayed_value": "delayed",
        "delayed_long_poll_waited": True,
    }
