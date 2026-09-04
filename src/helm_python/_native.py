"""Native library loading and the complete ctypes declaration table.

This is the only module that touches ctypes. Everything above it works with
Python types.

Two rules govern this file:

1. **Library-owned strings are typed ``c_void_p``, never ``c_char_p``.**
   ctypes silently converts a ``c_char_p`` result into a ``bytes`` object and
   discards the original pointer, which would make ``helm_free_string``
   impossible and leak every returned string. :func:`take_string` is the only
   sanctioned way to consume one: copy, then free.
2. **Signatures are declared once, here.** They are not re-declared per call,
   and ``scripts/check_native_table.py`` diffs this table against
   ``helm_c.h`` in CI so a drifted signature fails the build rather than
   corrupting memory at runtime.

The library is always loaded by *absolute path* (never by bare name through
the OS loader search path), so no ``LD_LIBRARY_PATH``/``DYLD_LIBRARY_PATH``/
``PATH`` configuration is required — see docs in the project README.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Any, Final

from .errors import HelmLibraryError, raise_for_code

__all__ = [
    "HANDLE",
    "LOG_CALLBACK",
    "SIGNATURES",
    "call_handle",
    "call_status",
    "call_status_no_error_out",
    "call_string",
    "helm_c_version",
    "helm_sdk_version",
    "lib",
    "library_path",
    "open_handles_count",
    "take_string",
]

# --- versions this binding is built against -------------------------------

#: helm-c-sdk release this binding is pinned to.
EXPECTED_HELM_C_VERSION: Final = "0.2.0"
#: Helm Go SDK compiled into that release.
EXPECTED_HELM_SDK_VERSION: Final = "v4.2.3"

# --- ctypes type aliases mirroring helm_c.h -------------------------------

#: ``helm_handle_t`` — opaque uint64 id into the library's handle registry.
HANDLE = ctypes.c_uint64
_HANDLE_OUT = ctypes.POINTER(ctypes.c_uint64)
#: ``char**`` out-parameter. Deliberately a void pointer (see module docs).
_STR_OUT = ctypes.POINTER(ctypes.c_void_p)
#: ``const char*`` input — borrowed by the library for the duration of a call.
_STR_IN = ctypes.c_char_p
_I32 = ctypes.c_int32
_I64 = ctypes.c_int64

#: ``helm_log_callback`` — void(int32 level, const char* message, void* user_data)
LOG_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_int32, ctypes.c_char_p, ctypes.c_void_p)

# --- the declaration table ------------------------------------------------
# name -> (restype, [argtypes])  — every exported symbol in helm_c.h.

SIGNATURES: Final[dict[str, tuple[Any, list[Any]]]] = {
    # library info
    "helm_c_version": (ctypes.c_void_p, []),
    "helm_sdk_version": (ctypes.c_void_p, []),
    # memory / lifecycle
    "helm_free_string": (None, [ctypes.c_void_p]),
    "helm_handle_free": (_I32, [HANDLE, _STR_OUT]),
    "helm_open_handles_count": (_I64, []),
    # chart utilities
    "helm_release_name_validate": (_I32, [_STR_IN, _STR_OUT]),
    "helm_strvals_parse": (_I32, [_STR_IN, _STR_OUT, _STR_OUT]),
    # charts (offline)
    "helm_chart_load": (_I32, [_STR_IN, _HANDLE_OUT, _STR_OUT]),
    "helm_chart_metadata": (_I32, [HANDLE, _STR_OUT, _STR_OUT]),
    "helm_chart_values": (_I32, [HANDLE, _STR_OUT, _STR_OUT]),
    "helm_chart_save": (_I32, [HANDLE, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_chart_create": (_I32, [_STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_chart_free": (_I32, [HANDLE, _STR_OUT]),
    "helm_lint_run": (_I32, [_STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_package_run": (_I32, [_STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    # values & rendering
    "helm_chart_merge_values": (_I32, [HANDLE, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_schema_validate": (_I32, [HANDLE, _STR_IN, _STR_OUT]),
    "helm_render": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    # OCI registry & distribution
    "helm_registry_client_new": (_I32, [_STR_IN, _HANDLE_OUT, _STR_OUT]),
    "helm_registry_client_free": (_I32, [HANDLE, _STR_OUT]),
    "helm_registry_login": (
        _I32,
        [HANDLE, _STR_IN, _STR_IN, _STR_IN, _STR_IN, _STR_OUT],
    ),
    "helm_registry_logout": (_I32, [HANDLE, _STR_IN, _STR_OUT]),
    "helm_pull": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_push": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_repo_index_download": (_I32, [_STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    # cluster configuration & cancellation
    "helm_config_new": (_I32, [_STR_IN, _HANDLE_OUT, _STR_OUT]),
    "helm_config_free": (_I32, [HANDLE, _STR_OUT]),
    "helm_context_new": (_I32, [_HANDLE_OUT, _STR_OUT]),
    "helm_context_cancel": (_I32, [HANDLE, _STR_OUT]),
    "helm_context_free": (_I32, [HANDLE, _STR_OUT]),
    # release actions
    "helm_install": (
        _I32,
        [HANDLE, HANDLE, HANDLE, _STR_IN, _STR_IN, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT],
    ),
    "helm_upgrade": (
        _I32,
        [HANDLE, HANDLE, HANDLE, _STR_IN, _STR_IN, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT],
    ),
    "helm_uninstall": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_rollback": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_OUT]),
    "helm_list": (_I32, [HANDLE, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_status": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_history": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_get_values": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_get_metadata": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    # dependencies & provenance
    "helm_dependency_update": (_I32, [_STR_IN, _STR_IN, _STR_OUT]),
    "helm_dependency_build": (_I32, [_STR_IN, _STR_IN, _STR_OUT]),
    "helm_chart_verify": (_I32, [_STR_IN, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    # charts (offline, 0.2.0 surface)
    "helm_chart_files": (_I32, [HANDLE, _STR_OUT, _STR_OUT]),
    "helm_chart_templates": (_I32, [HANDLE, _STR_OUT, _STR_OUT]),
    "helm_chart_crds": (_I32, [HANDLE, _STR_OUT, _STR_OUT]),
    "helm_chart_schema": (_I32, [HANDLE, _STR_OUT, _STR_OUT]),
    "helm_chart_dependencies": (_I32, [HANDLE, _STR_OUT, _STR_OUT]),
    "helm_chart_load_archive": (
        _I32,
        [ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint64, _HANDLE_OUT, _STR_OUT],
    ),
    "helm_chart_expand": (_I32, [_STR_IN, _STR_IN, _STR_OUT]),
    "helm_chart_save_dir": (_I32, [HANDLE, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_chart_create_from": (_I32, [_STR_IN, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_chart_digest": (_I32, [_STR_IN, _STR_OUT, _STR_OUT]),
    "helm_chart_sign": (_I32, [_STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_values_from_yaml": (_I32, [_STR_IN, _STR_OUT, _STR_OUT]),
    "helm_lint_run_opts": (_I32, [_STR_IN, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_render_with_config": (
        _I32,
        [HANDLE, HANDLE, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT],
    ),
    # --set expression family (0.2.0 surface)
    "helm_strvals_parse_string": (_I32, [_STR_IN, _STR_OUT, _STR_OUT]),
    "helm_strvals_parse_json": (_I32, [_STR_IN, _STR_OUT, _STR_OUT]),
    "helm_strvals_parse_literal": (_I32, [_STR_IN, _STR_OUT, _STR_OUT]),
    "helm_strvals_parse_file": (_I32, [_STR_IN, _STR_OUT, _STR_OUT]),
    # distribution (0.2.0 surface)
    "helm_show": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_repo_index_generate": (_I32, [_STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_dependency_list": (_I32, [_STR_IN, _STR_OUT, _STR_OUT]),
    "helm_registry_tags": (_I32, [HANDLE, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_registry_resolve": (_I32, [HANDLE, _STR_IN, _STR_OUT, _STR_OUT]),
    # cluster (0.2.0 surface)
    "helm_config_set_registry_client": (_I32, [HANDLE, HANDLE, _STR_OUT]),
    "helm_config_check_reachable": (_I32, [HANDLE, _STR_OUT]),
    "helm_get": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    "helm_test_run": (_I32, [HANDLE, _STR_IN, _STR_IN, _STR_OUT, _STR_OUT]),
    # logging
    "helm_set_log_handler": (_I32, [LOG_CALLBACK, ctypes.c_void_p, _I32]),
}


# --- locating the library -------------------------------------------------


def _library_names() -> list[str]:
    """Filenames to look for, most specific first, for this platform."""
    if sys.platform == "win32":
        return [
            f"libhelm_c-{EXPECTED_HELM_C_VERSION}.dll",
            "libhelm_c.dll",
            "helm_c.dll",
        ]
    if sys.platform == "darwin":
        major = EXPECTED_HELM_C_VERSION.split(".")[0]
        return [
            f"libhelm_c.{EXPECTED_HELM_C_VERSION}.dylib",
            f"libhelm_c.{major}.dylib",
            "libhelm_c.dylib",
        ]
    major = EXPECTED_HELM_C_VERSION.split(".")[0]
    return [
        f"libhelm_c.so.{EXPECTED_HELM_C_VERSION}",
        f"libhelm_c.so.{major}",
        "libhelm_c.so",
    ]


def _candidate_paths() -> list[Path]:
    """Absolute paths to try, in priority order.

    1. ``HELM_C_LIB`` — an explicit file (or directory) the user supplied,
       e.g. a library they built themselves.
    2. The ``lib/`` directory packaged inside this distribution.
    """
    candidates: list[Path] = []

    override = os.environ.get("HELM_C_LIB")
    if override:
        # Absolute from here on. A relative override would otherwise be
        # re-resolved by the loader against the process's current directory,
        # so the file we checked and the file ctypes opens could differ, and
        # the reported library_path would go stale on the first chdir.
        path = Path(override).expanduser().resolve()
        if path.is_dir():
            candidates.extend(path / name for name in _library_names())
        else:
            candidates.append(path)

    packaged = Path(__file__).resolve().parent / "lib"
    candidates.extend(packaged / name for name in _library_names())
    return candidates


def _load() -> tuple[ctypes.CDLL, Path]:
    tried = _candidate_paths()
    for path in tried:
        if path.is_file():
            try:
                return ctypes.CDLL(str(path)), path
            except OSError as exc:  # wrong arch, missing system deps, ...
                raise HelmLibraryError(
                    f"found the helm-c library at {path} but could not load it: {exc}. "
                    "This usually means the binary was built for a different "
                    "architecture or libc. Set HELM_C_LIB to a library built for "
                    "this system, or reinstall with HELM_PYTHON_BUILD=1 to build "
                    "from source."
                ) from exc

    searched = "\n  ".join(str(p) for p in tried)
    raise HelmLibraryError(
        "could not find the helm-c native library. Searched:\n  "
        f"{searched}\n"
        "Install a wheel for this platform, set HELM_C_LIB=/path/to/libhelm_c.<ext>, "
        "or reinstall with HELM_PYTHON_BUILD=1 to build it from source."
    )


def _declare(library: ctypes.CDLL) -> None:
    """Apply the signature table; a missing symbol means a wrong library."""
    for name, (restype, argtypes) in SIGNATURES.items():
        try:
            func = getattr(library, name)
        except AttributeError as exc:
            raise HelmLibraryError(
                f"the loaded library does not export {name!r}; it is not a "
                f"helm-c library of version {EXPECTED_HELM_C_VERSION}"
            ) from exc
        func.restype = restype
        func.argtypes = argtypes


lib: ctypes.CDLL
library_path: Path
lib, library_path = _load()
_declare(lib)


# --- string ownership -----------------------------------------------------


def take_string(ptr: int | None) -> str | None:
    """Consume a library-owned ``char*``: copy it to ``str``, then free it.

    ``ptr`` is the integer address held by a ``c_void_p`` (``None`` when the
    library returned NULL). The pointer is freed exactly once, even if
    decoding raises.
    """
    if not ptr:
        return None
    try:
        return ctypes.string_at(ptr).decode("utf-8")
    finally:
        lib.helm_free_string(ctypes.c_void_p(ptr))


def _encode(value: str | None) -> bytes | None:
    """UTF-8 encode an optional input string; ``None`` stays NULL."""
    return None if value is None else value.encode("utf-8")


# --- call helpers ---------------------------------------------------------
# Each appends the out-parameters the ABI expects, checks the status code,
# and converts ownership correctly.


def call_status(func_name: str, *args: Any) -> None:
    """Invoke a shim whose only output is its status code."""
    func = getattr(lib, func_name)
    err = ctypes.c_void_p()
    code = func(*_prepare(args), ctypes.byref(err))
    raise_for_code(code, take_string(err.value))


def call_string(func_name: str, *args: Any) -> str:
    """Invoke a shim returning one caller-owned string, and own it properly."""
    func = getattr(lib, func_name)
    out = ctypes.c_void_p()
    err = ctypes.c_void_p()
    code = func(*_prepare(args), ctypes.byref(out), ctypes.byref(err))
    detail = take_string(err.value)
    result = take_string(out.value)
    raise_for_code(code, detail)
    return result or ""


def call_status_no_error_out(func_name: str, *args: Any) -> None:
    """Invoke a shim that returns a status but takes no ``error_out``.

    Only ``helm_set_log_handler`` has this shape; everything else reports
    detail through an out-parameter.
    """
    func = getattr(lib, func_name)
    raise_for_code(int(func(*args)), None)


def call_handle(func_name: str, *args: Any) -> int:
    """Invoke a shim returning a new handle."""
    func = getattr(lib, func_name)
    out = ctypes.c_uint64()
    err = ctypes.c_void_p()
    code = func(*_prepare(args), ctypes.byref(out), ctypes.byref(err))
    raise_for_code(code, take_string(err.value))
    return int(out.value)


def _prepare(args: tuple[Any, ...]) -> list[Any]:
    """Encode ``str`` arguments; pass everything else through untouched."""
    return [_encode(a) if isinstance(a, str) or a is None else a for a in args]


# --- library info ---------------------------------------------------------


def helm_c_version() -> str:
    """Version of the loaded helm-c library."""
    return take_string(lib.helm_c_version()) or "unknown"


def helm_sdk_version() -> str:
    """Helm Go SDK version compiled into the loaded library."""
    return take_string(lib.helm_sdk_version()) or "unknown"


def open_handles_count() -> int:
    """Number of live handles — used by the test suite's leak gate."""
    return int(lib.helm_open_handles_count())


def _check_versions() -> None:
    """Fail loudly on a library too different from what we declare against."""
    loaded = helm_c_version()
    expected_major = EXPECTED_HELM_C_VERSION.split(".")[0]
    if loaded.split(".")[0] != expected_major:
        raise HelmLibraryError(
            f"helm-c library version {loaded} is incompatible with this binding "
            f"(built for {EXPECTED_HELM_C_VERSION}); its C ABI may differ. "
            "Install a matching library or upgrade helm-python."
        )


_check_versions()
