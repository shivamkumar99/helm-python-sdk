"""Test configuration.

Locates the native library for development runs and enforces the leak gate:
no test may leave a live handle behind.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Development convenience: when HELM_C_LIB is not set, use the sibling
# helm-c checkout's build output. CI and installed users rely on the wheel's
# packaged library instead.
if "HELM_C_LIB" not in os.environ:
    sibling = Path(__file__).resolve().parents[2] / "helm-c" / "build"
    if sibling.is_dir():
        os.environ["HELM_C_LIB"] = str(sibling)

import helm_python


@pytest.fixture(autouse=True)
def _leak_gate() -> None:
    """Every test must free every handle it creates."""
    before = helm_python.open_handles_count()
    yield
    after = helm_python.open_handles_count()
    assert after == before, f"test leaked {after - before} handle(s)"


@pytest.fixture(scope="session", autouse=True)
def _session_leak_gate() -> None:
    yield
    assert helm_python.open_handles_count() == 0, "session ended with live handles"
