"""The loader explains a musl system instead of sending people in circles.

Go cannot yet build a c-shared library musl's loader will dlopen
(golang/go#54805), so on Alpine the library either is not there or does
not load. The generic advice — "reinstall with HELM_PYTHON_BUILD=1" —
would make a user compile Go for several minutes and hit the same wall,
so both paths have to name musl instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helm_python import _native
from helm_python.errors import HelmLibraryError


def test_musl_load_failure_is_named_not_guessed() -> None:
    message = _native._load_failure(
        Path("/opt/lib/libhelm_c.so"),
        OSError(
            "Error relocating /opt/lib/libhelm_c.so: runtime.tls_g: "
            "initial-exec TLS resolves to dynamic definition"
        ),
    )
    assert "musl" in message
    assert "golang/go#54805" in message
    # The advice that cannot work here must not appear.
    assert "HELM_PYTHON_BUILD=1" not in message


def test_other_load_failures_keep_the_general_advice() -> None:
    message = _native._load_failure(
        Path("/opt/lib/libhelm_c.so"), OSError("wrong ELF class: ELFCLASS32")
    )
    assert "HELM_PYTHON_BUILD=1" in message
    assert "musl" not in message


def test_musl_detection_is_false_on_this_platform() -> None:
    # The suite runs on glibc, macOS, and Windows; musl would mean the
    # library could not have loaded to run this test at all.
    assert _native.on_musl() is False


def test_missing_library_on_musl_explains_rather_than_suggesting_a_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_native, "on_musl", lambda: True)
    monkeypatch.setattr(_native, "_candidate_paths", lambda: [Path("/nonexistent/libhelm_c.so")])
    with pytest.raises(HelmLibraryError) as caught:
        _native._load()
    message = str(caught.value)
    assert "musl" in message
    assert "golang/go#54805" in message
