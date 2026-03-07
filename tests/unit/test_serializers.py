"""Unit tests for serializer implementations."""

from __future__ import annotations

import pytest

from simpleq.exceptions import SerializationError
from simpleq.serializers import CloudpickleSerializer, JSONSerializer, get_serializer
from tests.fixtures.tasks import EmailPayload


def test_json_serializer_roundtrip_model() -> None:
    serializer = JSONSerializer()
    payload = serializer.dump(
        EmailPayload(to="a@example.com", subject="Hi", body="Body")
    )
    restored = serializer.load(payload)
    assert restored == {"to": "a@example.com", "subject": "Hi", "body": "Body"}


def test_json_serializer_raises_for_unknown_object() -> None:
    serializer = JSONSerializer()
    with pytest.raises(SerializationError):
        serializer.dump(object())


def test_cloudpickle_serializer_roundtrip() -> None:
    serializer = CloudpickleSerializer()
    payload = serializer.dump({"items": {1, 2, 3}})
    restored = serializer.load(payload)
    assert restored == {"items": {1, 2, 3}}


def test_get_serializer_rejects_unknown_name() -> None:
    with pytest.raises(SerializationError):
        get_serializer("xml")


def test_cloudpickle_serializer_rejects_non_string_payload() -> None:
    with pytest.raises(SerializationError):
        CloudpickleSerializer().load({"bad": "payload"})
