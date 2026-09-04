"""Bridge the library's internal logging into Python's :mod:`logging`.

The library is silent until you opt in:

    >>> import logging, helm_python as helm
    >>> logging.basicConfig(level=logging.DEBUG)
    >>> helm.enable_logging(logging.DEBUG)

Records are emitted on the ``helm_python.native`` logger, so they can be
filtered and routed like any other Python logging.

Two details matter here and are handled for you:

* the C callback object is kept referenced for as long as it is installed —
  if it were collected, the library would call into freed memory;
* callbacks arrive on **arbitrary Go threads**. ctypes acquires the GIL
  before entering Python, and nothing is allowed to propagate back into C,
  so a broken logging handler can never crash the process.
"""

from __future__ import annotations

import logging
from typing import Any

from . import _native

__all__ = ["disable_logging", "enable_logging"]

#: Records are emitted here.
LOGGER_NAME = "helm_python.native"

# helm_log_level -> Python level
_TO_PYTHON = {
    0: logging.DEBUG,
    1: logging.INFO,
    2: logging.WARNING,
    3: logging.ERROR,
}

# Python level -> the minimum helm_log_level worth forwarding.
_HELM_DEBUG, _HELM_INFO, _HELM_WARN, _HELM_ERROR = 0, 1, 2, 3


def _to_helm_level(level: int) -> int:
    if level <= logging.DEBUG:
        return _HELM_DEBUG
    if level <= logging.INFO:
        return _HELM_INFO
    if level <= logging.WARNING:
        return _HELM_WARN
    return _HELM_ERROR


# The installed callback must stay referenced: the library holds a raw
# function pointer, so letting this be collected would be a use-after-free.
_installed_callback: Any = None
_target_logger: logging.Logger | None = None


def _dispatch(level: int, message: bytes | None, _user_data: Any) -> None:
    """Forward one record. Never raises — this runs inside a C callback."""
    try:
        logger = _target_logger or logging.getLogger(LOGGER_NAME)
        text = message.decode("utf-8", errors="replace") if message else ""
        logger.log(_TO_PYTHON.get(level, logging.INFO), "%s", text)
    # A callback must never raise back into C.
    except Exception:  # nosec B110
        pass


def enable_logging(level: int = logging.INFO, logger: logging.Logger | None = None) -> None:
    """Route the library's log records into Python logging.

    Applies to :class:`~helm_python.Config` objects created *afterwards*, so
    call this before building a config.

    Args:
        level: the minimum Python level to forward. Records below it are
            dropped inside the library and never cross into Python.
        logger: where to emit; defaults to the ``helm_python.native`` logger.
    """
    global _installed_callback, _target_logger

    _target_logger = logger
    callback = _native.LOG_CALLBACK(_dispatch)
    _native.call_status_no_error_out("helm_set_log_handler", callback, None, _to_helm_level(level))
    # Only keep the new callback once the library has accepted it.
    _installed_callback = callback


def disable_logging() -> None:
    """Stop forwarding records; the library goes silent again."""
    global _installed_callback, _target_logger

    # A NULL function pointer, not None: ctypes will not coerce None for a
    # CFUNCTYPE parameter.
    _native.call_status_no_error_out("helm_set_log_handler", _native.LOG_CALLBACK(), None, 0)
    _installed_callback = None
    _target_logger = None
