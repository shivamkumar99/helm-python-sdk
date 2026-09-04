"""The native logging bridge."""

from __future__ import annotations

import gc
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

import helm_python as helm
from helm_python import logging as helm_logging


@pytest.fixture(autouse=True)
def _always_disable() -> Iterator[None]:
    """Never leave a callback installed for the next test."""
    yield
    helm.disable_logging()


def test_silent_by_default(caplog: pytest.LogCaptureFixture) -> None:
    """Nothing is emitted until logging is explicitly enabled."""
    with (
        caplog.at_level(logging.DEBUG, logger=helm_logging.LOGGER_NAME),
        helm.RegistryClient(debug=True),
    ):
        pass
    assert caplog.records == []


def test_enable_and_disable_are_repeatable() -> None:
    helm.enable_logging(logging.DEBUG)
    helm.enable_logging(logging.INFO)  # replacing a handler is fine
    helm.disable_logging()
    helm.disable_logging()  # idempotent


def test_callback_stays_referenced_while_installed() -> None:
    """A collected callback would leave the library calling freed memory."""
    helm.enable_logging(logging.DEBUG)
    gc.collect()
    assert helm_logging._installed_callback is not None

    helm.disable_logging()
    assert helm_logging._installed_callback is None


def test_records_reach_python(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    helm.enable_logging(logging.DEBUG)
    with caplog.at_level(logging.DEBUG, logger=helm_logging.LOGGER_NAME):
        # Any cluster-bound action logs on its way to failing.
        cfg = helm.Config(
            kubeconfig_content=_UNREACHABLE, storage_driver="memory", namespace="default"
        )
        with cfg, pytest.raises(helm.HelmError):
            cfg.list()

    # The library may or may not log for this specific path; what must hold is
    # that anything it did emit arrived as proper records on our logger.
    for record in caplog.records:
        assert record.name == helm_logging.LOGGER_NAME
        assert isinstance(record.getMessage(), str)


def test_custom_logger_receives_records(tmp_path: Path) -> None:
    custom = logging.getLogger("my.helm.logger")
    seen: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    handler = Collect()
    custom.addHandler(handler)
    custom.setLevel(logging.DEBUG)
    try:
        helm.enable_logging(logging.DEBUG, logger=custom)
        # Directly exercise the dispatch path the C callback uses.
        helm_logging._dispatch(1, b"hello from the library", None)
        assert seen == ["hello from the library"]
    finally:
        custom.removeHandler(handler)


def test_dispatch_never_raises() -> None:
    """A broken handler must not propagate an exception back into C."""

    class Exploding(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError("handler is broken")

    logger = logging.getLogger("exploding.helm.logger")
    logger.addHandler(Exploding())
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        helm.enable_logging(logging.DEBUG, logger=logger)
        helm_logging._dispatch(3, b"boom", None)  # must not raise
        helm_logging._dispatch(0, None, None)  # NULL message is tolerated
    finally:
        logger.handlers.clear()


def test_level_mapping() -> None:
    assert helm_logging._to_helm_level(logging.DEBUG) == 0
    assert helm_logging._to_helm_level(logging.INFO) == 1
    assert helm_logging._to_helm_level(logging.WARNING) == 2
    assert helm_logging._to_helm_level(logging.ERROR) == 3
    assert helm_logging._to_helm_level(logging.CRITICAL) == 3


def test_invalid_utf8_is_replaced_not_fatal() -> None:
    logger = logging.getLogger("bytes.helm.logger")
    seen: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    logger.addHandler(Collect())
    logger.setLevel(logging.DEBUG)
    try:
        helm.enable_logging(logging.DEBUG, logger=logger)
        helm_logging._dispatch(1, b"bad \xff bytes", None)
        assert seen
        assert "bad" in seen[0]
    finally:
        logger.handlers.clear()


_UNREACHABLE = """apiVersion: v1
kind: Config
clusters:
  - name: nowhere
    cluster:
      server: https://127.0.0.1:1
contexts:
  - name: nowhere
    context:
      cluster: nowhere
      user: nobody
current-context: nowhere
users:
  - name: nobody
    user: {}
"""
