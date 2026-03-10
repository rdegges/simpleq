"""Unit tests for pytest collection behavior in tests.conftest."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import tests.conftest as suite_conftest


@dataclass
class ConfigStub:
    """Minimal config stub supporting getoption calls."""

    options: dict[str, bool]

    def getoption(self, name: str) -> bool:
        return self.options[name]


@dataclass
class ItemStub:
    """Minimal pytest item stub for marker assertions."""

    keyword_names: set[str]
    keywords: dict[str, bool] = field(init=False)
    markers: list[Any] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.keywords = dict.fromkeys(self.keyword_names, True)

    def add_marker(self, marker: Any) -> None:
        self.markers.append(marker)


def _has_skip_with_reason(item: ItemStub, reason_fragment: str) -> bool:
    for marker in item.markers:
        if marker.name != "skip":
            continue
        reason = marker.kwargs.get("reason", "")
        if reason_fragment in reason:
            return True
    return False


def test_collection_skips_live_tests_without_flag(monkeypatch) -> None:
    monkeypatch.setattr(suite_conftest, "_is_endpoint_reachable", lambda _: True)
    config = ConfigStub({"--run-live-aws": False})
    live_item = ItemStub({"live"})

    suite_conftest.pytest_collection_modifyitems(config, [live_item])  # type: ignore[arg-type]

    assert _has_skip_with_reason(live_item, "--run-live-aws")


def test_collection_skips_integration_when_localstack_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(suite_conftest, "_is_endpoint_reachable", lambda _: False)
    config = ConfigStub({"--run-live-aws": True})
    integration_item = ItemStub({"integration"})

    suite_conftest.pytest_collection_modifyitems(  # type: ignore[arg-type]
        config,
        [integration_item],
    )

    assert _has_skip_with_reason(integration_item, "LocalStack endpoint")


def test_collection_does_not_skip_integration_when_endpoint_reachable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(suite_conftest, "_is_endpoint_reachable", lambda _: True)
    config = ConfigStub({"--run-live-aws": True})
    integration_item = ItemStub({"integration"})

    suite_conftest.pytest_collection_modifyitems(  # type: ignore[arg-type]
        config,
        [integration_item],
    )

    assert integration_item.markers == []
