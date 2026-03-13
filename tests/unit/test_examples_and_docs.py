"""Smoke tests for examples, generated scaffolds, and quick-start docs."""

from __future__ import annotations

import re
import runpy
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import simpleq as simpleq_package
from simpleq import SimpleQ
from simpleq.cli import app
from simpleq.testing import InMemoryTransport

ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


class InMemorySimpleQ(SimpleQ):
    """SimpleQ subclass that always uses the in-memory test transport."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("transport", InMemoryTransport())
        super().__init__(*args, **kwargs)


def _patch_simpleq(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(simpleq_package, "SimpleQ", InMemorySimpleQ)


def _extract_python_block(document: Path, heading: str) -> str:
    content = document.read_text(encoding="utf-8")
    start = content.index(heading)
    match = re.search(r"```python\n(.*?)\n```", content[start:], re.DOTALL)
    if match is None:
        raise AssertionError(f"Could not find a Python block after {heading!r}.")
    return match.group(1)


def _run_python_file(path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_simpleq(monkeypatch)
    runpy.run_path(str(path), run_name="__main__")


def _run_markdown_example(
    document: Path,
    heading: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_simpleq(monkeypatch)
    code = _extract_python_block(document, heading)
    namespace = {"__name__": "__main__", "__file__": str(document)}
    exec(compile(code, str(document), "exec"), namespace)


def test_basic_example_runs_with_inmemory_transport(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_python_file(ROOT / "examples/basic.py", monkeypatch)

    assert "sent user@example.com" in capsys.readouterr().out


def test_simpleq_init_scaffold_runs_with_inmemory_transport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "demo"
    result = runner.invoke(app, ["init", str(target)])

    assert result.exit_code == 0

    _run_python_file(target / "simpleq_app.py", monkeypatch)

    assert "Sending Hello to user@example.com" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("document", "heading", "expected_output"),
    [
        (
            ROOT / "README.md",
            "## Quick Start",
            "Sending Hello to user@example.com",
        ),
        (
            ROOT / "docs/quickstart.md",
            "## Sync-first example",
            "user@example.com",
        ),
    ],
)
def test_quickstart_markdown_examples_run(
    document: Path,
    heading: str,
    expected_output: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_markdown_example(document, heading, monkeypatch)

    assert expected_output in capsys.readouterr().out
