"""Ownership of native handles.

Every stateful object the library hands out is a ``uint64`` handle that must
be freed exactly once. :class:`NativeHandle` gives those objects Python
lifetimes:

* a context manager (``with``) for deterministic release;
* an explicit, idempotent :meth:`~NativeHandle.close`;
* a :mod:`weakref` finalizer as the safety net, so a forgotten object is
  still freed when it is collected or at interpreter exit.

The finalizer is safe because the C ABI guarantees frees are idempotent and
tolerate unknown handles: a double free returns an error code rather than
crashing, so a race between ``close()`` and garbage collection cannot corrupt
anything.
"""

from __future__ import annotations

import contextlib
import weakref
from types import TracebackType
from typing import ClassVar, TypeVar

from . import _native
from .errors import HelmError

__all__ = ["NativeHandle"]

# ``typing.Self`` needs 3.11 and typing_extensions is not a dependency, so a
# bound TypeVar expresses "returns its own type" for subclasses on 3.10.
_HandleT = TypeVar("_HandleT", bound="NativeHandle")


def _release(free_func: str, handle: int) -> None:
    """Free a handle, ignoring failures.

    Runs from ``close()`` and from garbage collection. Raising during
    collection is not useful (the exception would be printed and discarded),
    and the only expected failure is "already freed".
    """
    with contextlib.suppress(HelmError):
        _native.call_status(free_func, _native.HANDLE(handle))


class NativeHandle:
    """Base class for objects that own a native handle."""

    #: Name of the C function that frees this handle type.
    _free_func: ClassVar[str] = "helm_handle_free"
    #: Human-readable type name used in error messages.
    _kind: ClassVar[str] = "object"

    __slots__ = ("__weakref__", "_finalizer", "_handle")

    def __init__(self, handle: int) -> None:
        self._handle = handle
        self._finalizer = weakref.finalize(self, _release, self._free_func, handle)

    @property
    def closed(self) -> bool:
        """``True`` once the handle has been released."""
        return not self._finalizer.alive

    def close(self) -> None:
        """Release the handle. Safe to call more than once."""
        self._finalizer()

    def _raw(self) -> object:
        """The handle as a ctypes value, or raise if it is already closed."""
        if self.closed:
            raise HelmError(f"this {self._kind} is closed")
        return _native.HANDLE(self._handle)

    def __enter__(self: _HandleT) -> _HandleT:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "closed" if self.closed else f"handle={self._handle}"
        return f"<{type(self).__name__} {state}>"
