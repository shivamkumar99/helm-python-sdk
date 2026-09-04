"""Exception hierarchy mapped from the C ABI's ``helm_error_code`` enum.

Every failing library call raises a subclass of :class:`HelmError` carrying the
numeric ``code`` and the detail message the library produced. The numeric
codes are ABI: they are append-only upstream and never renumbered, so the
mapping below is stable.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = [
    "ErrorCode",
    "HelmCancelledError",
    "HelmChartInvalidError",
    "HelmChartLoadError",
    "HelmError",
    "HelmIOError",
    "HelmInvalidArgError",
    "HelmInvalidHandleError",
    "HelmKubeError",
    "HelmLibraryError",
    "HelmNotFoundError",
    "HelmPanicError",
    "HelmRegistryError",
    "HelmReleaseError",
    "HelmRenderError",
    "HelmRepoError",
    "HelmStorageError",
    "HelmUnknownError",
    "HelmValuesError",
    "HelmWrongHandleTypeError",
    "raise_for_code",
]


class ErrorCode(IntEnum):
    """Mirrors ``helm_error_code`` in helm_c.h."""

    OK = 0
    UNKNOWN = -1
    INVALID_ARG = -2
    INVALID_HANDLE = -3
    WRONG_HANDLE_TYPE = -4
    PANIC = -5
    CANCELLED = -6
    NOT_FOUND = -7
    IO = -8
    CHART_LOAD = -20
    CHART_INVALID = -21
    VALUES = -22
    RENDER = -23
    REGISTRY = -40
    REPO = -41
    KUBE = -60
    STORAGE = -61
    RELEASE = -62


class HelmError(Exception):
    """Base class for every error raised by this package.

    Attributes:
        code: the numeric ``helm_error_code`` returned by the library, or
            ``None`` for errors raised on the Python side (e.g. loading).
        detail: the library's human-readable message, if any.
    """

    code: int | None = None

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.detail = message
        if code is not None:
            self.code = code


class HelmLibraryError(HelmError):
    """The native library could not be located, loaded, or validated."""


class HelmUnknownError(HelmError):
    """The library reported a failure with no more specific code."""

    code = ErrorCode.UNKNOWN


class HelmInvalidArgError(HelmError, ValueError):
    """An argument was missing, malformed, or an unknown option key was used."""

    code = ErrorCode.INVALID_ARG


class HelmInvalidHandleError(HelmError):
    """The handle is unknown or was already freed."""

    code = ErrorCode.INVALID_HANDLE


class HelmWrongHandleTypeError(HelmError):
    """The handle exists but holds a different object type."""

    code = ErrorCode.WRONG_HANDLE_TYPE


class HelmPanicError(HelmError):
    """The library recovered an internal panic — please report this."""

    code = ErrorCode.PANIC


class HelmCancelledError(HelmError):
    """The operation was cancelled through its context."""

    code = ErrorCode.CANCELLED


class HelmNotFoundError(HelmError, LookupError):
    """The requested release (or other object) does not exist."""

    code = ErrorCode.NOT_FOUND


class HelmIOError(HelmError, OSError):
    """A filesystem operation failed."""

    code = ErrorCode.IO


class HelmChartLoadError(HelmError):
    """A chart could not be read from the given path or archive."""

    code = ErrorCode.CHART_LOAD


class HelmChartInvalidError(HelmError):
    """A chart failed validation, packaging, or provenance verification."""

    code = ErrorCode.CHART_INVALID


class HelmValuesError(HelmError, ValueError):
    """Values were malformed or failed schema validation."""

    code = ErrorCode.VALUES


class HelmRenderError(HelmError):
    """Template rendering failed."""

    code = ErrorCode.RENDER


class HelmRegistryError(HelmError):
    """An OCI registry operation failed (auth, push, pull)."""

    code = ErrorCode.REGISTRY


class HelmRepoError(HelmError):
    """A chart-repository operation failed (index, pull, dependencies)."""

    code = ErrorCode.REPO


class HelmKubeError(HelmError):
    """Kubernetes client configuration or connectivity failed."""

    code = ErrorCode.KUBE


class HelmStorageError(HelmError):
    """The release storage backend failed."""

    code = ErrorCode.STORAGE


class HelmReleaseError(HelmError):
    """A release action failed (install, upgrade, rollback, ...)."""

    code = ErrorCode.RELEASE


_BY_CODE: dict[int, type[HelmError]] = {
    ErrorCode.UNKNOWN: HelmUnknownError,
    ErrorCode.INVALID_ARG: HelmInvalidArgError,
    ErrorCode.INVALID_HANDLE: HelmInvalidHandleError,
    ErrorCode.WRONG_HANDLE_TYPE: HelmWrongHandleTypeError,
    ErrorCode.PANIC: HelmPanicError,
    ErrorCode.CANCELLED: HelmCancelledError,
    ErrorCode.NOT_FOUND: HelmNotFoundError,
    ErrorCode.IO: HelmIOError,
    ErrorCode.CHART_LOAD: HelmChartLoadError,
    ErrorCode.CHART_INVALID: HelmChartInvalidError,
    ErrorCode.VALUES: HelmValuesError,
    ErrorCode.RENDER: HelmRenderError,
    ErrorCode.REGISTRY: HelmRegistryError,
    ErrorCode.REPO: HelmRepoError,
    ErrorCode.KUBE: HelmKubeError,
    ErrorCode.STORAGE: HelmStorageError,
    ErrorCode.RELEASE: HelmReleaseError,
}


def exception_for_code(code: int) -> type[HelmError]:
    """Return the exception class registered for a ``helm_error_code``.

    Unmapped (e.g. newly added) codes fall back to :class:`HelmUnknownError`,
    so a library newer than this binding still raises something sensible.
    """
    return _BY_CODE.get(code, HelmUnknownError)


def raise_for_code(code: int, detail: str | None) -> None:
    """Raise the mapped exception for a non-zero status code.

    Does nothing when ``code`` is :attr:`ErrorCode.OK`.
    """
    if code == ErrorCode.OK:
        return
    message = detail or f"helm-c call failed with code {code}"
    raise exception_for_code(code)(message, code=code)
