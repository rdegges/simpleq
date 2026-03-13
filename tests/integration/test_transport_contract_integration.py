"""Integration parity tests for LocalStack and InMemoryTransport."""

from __future__ import annotations

import pytest

from simpleq import SimpleQ
from simpleq.testing import InMemoryTransport
from tests.fixtures.transport_contract import transport_contract_summary


@pytest.mark.integration
@pytest.mark.asyncio
async def test_localstack_matches_inmemory_transport_contract(
    simpleq_localstack,
    unique_name,
    cleanup_queues,
) -> None:
    base_name = unique_name("transport-contract")

    inmemory_summary = await transport_contract_summary(
        SimpleQ(transport=InMemoryTransport()),
        base_name=base_name,
        include_receive_attempt_replay=False,
    )
    localstack_summary = await transport_contract_summary(
        simpleq_localstack,
        base_name=base_name,
        cleanup_queues=cleanup_queues,
        include_receive_attempt_replay=False,
    )

    assert localstack_summary == inmemory_summary
