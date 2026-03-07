"""Serializer implementations for SimpleQ task payloads."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias, cast

import cloudpickle  # type: ignore[import-untyped]
from pydantic import TypeAdapter

from simpleq.exceptions import SerializationError

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

_ANY_ADAPTER = TypeAdapter(Any)


class Serializer(Protocol):
    """Protocol implemented by all serializers."""

    name: str

    def dump(self, value: Any) -> JSONValue:
        """Serialize a Python value into a JSON-compatible value."""

    def load(self, value: JSONValue) -> Any:
        """Deserialize a JSON-compatible value back into Python."""


@dataclass(frozen=True, slots=True)
class JSONSerializer:
    """Safe JSON serializer for task payloads."""

    name: str = "json"

    def dump(self, value: Any) -> JSONValue:
        try:
            normalized = _ANY_ADAPTER.dump_python(value, mode="json")
        except Exception as exc:  # pragma: no cover - exercised by tests
            raise SerializationError(str(exc)) from exc
        return cast("JSONValue", normalized)

    def load(self, value: JSONValue) -> Any:
        try:
            return json.loads(json.dumps(value))
        except Exception as exc:  # pragma: no cover - exercised by tests
            raise SerializationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class CloudpickleSerializer:
    """Opt-in serializer for non-JSON task payloads."""

    name: str = "cloudpickle"

    def dump(self, value: Any) -> JSONValue:
        encoded = base64.b64encode(cloudpickle.dumps(value)).decode("ascii")
        return encoded

    def load(self, value: JSONValue) -> Any:
        if not isinstance(value, str):
            raise SerializationError("Cloudpickle payloads must be base64 strings.")
        return cloudpickle.loads(base64.b64decode(value.encode("ascii")))


SERIALIZERS: dict[str, Serializer] = {
    "json": cast("Serializer", JSONSerializer()),
    "cloudpickle": cast("Serializer", CloudpickleSerializer()),
}


def get_serializer(name: str | None) -> Serializer:
    """Resolve a serializer by name."""
    resolved = name or "json"
    try:
        return SERIALIZERS[resolved]
    except KeyError as exc:
        raise SerializationError(f"Unknown serializer: {resolved}") from exc
