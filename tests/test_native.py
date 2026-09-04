"""The native layer: declaration table, loading, and string ownership."""

from __future__ import annotations

import ctypes
from pathlib import Path

import pytest

import helm_python
from helm_python import _native


def test_all_declared_symbols_exist_in_the_library() -> None:
    for name in _native.SIGNATURES:
        func = getattr(_native.lib, name)
        restype, argtypes = _native.SIGNATURES[name]
        assert func.restype is restype
        assert list(func.argtypes) == argtypes


def test_returned_strings_are_never_typed_c_char_p() -> None:
    """c_char_p would copy and lose the pointer, making free impossible."""
    for name, (restype, argtypes) in _native.SIGNATURES.items():
        assert restype is not ctypes.c_char_p, f"{name} returns c_char_p"
        for argtype in argtypes:
            assert argtype is not ctypes.POINTER(ctypes.c_char_p), (
                f"{name} takes a char** out-param typed c_char_p"
            )


def test_library_loaded_from_absolute_path() -> None:
    assert _native.library_path.is_absolute()
    assert _native.library_path.is_file()


def test_a_relative_override_is_made_absolute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """HELM_C_LIB may be relative; every candidate must still be absolute.

    ctypes resolves a relative path against the process's current directory,
    so a relative candidate could load a different file than the one checked,
    and library_path would go stale after any chdir.
    """
    libdir = tmp_path / "build"
    libdir.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HELM_C_LIB", "build")

    candidates = _native._candidate_paths()

    assert candidates, "an override must produce candidates"
    assert all(c.is_absolute() for c in candidates), (
        f"relative candidates: {[str(c) for c in candidates if not c.is_absolute()]}"
    )
    assert any(c.parent == libdir.resolve() for c in candidates)


def test_versions_reported() -> None:
    assert helm_python.helm_c_version() == _native.EXPECTED_HELM_C_VERSION
    assert helm_python.helm_sdk_version().startswith("v4.")


def test_take_string_handles_null() -> None:
    assert _native.take_string(None) is None
    assert _native.take_string(0) is None


def test_take_string_copies_and_frees() -> None:
    """The returned str must survive the free that follows it."""
    ptr = _native.lib.helm_c_version()
    value = _native.take_string(ptr)
    assert value == _native.EXPECTED_HELM_C_VERSION
    # Repeating many times would grow memory if the free were skipped.
    for _ in range(1000):
        _native.take_string(_native.lib.helm_c_version())


def test_open_handles_count_is_zero_at_rest() -> None:
    assert helm_python.open_handles_count() == 0


def test_call_status_raises_mapped_exception() -> None:
    with pytest.raises(helm_python.HelmInvalidArgError):
        _native.call_status("helm_release_name_validate", "Invalid_NAME!")


def test_call_string_returns_owned_value() -> None:
    result = _native.call_string("helm_strvals_parse", "a=1")
    assert result == '{"a":1}'


def test_call_handle_and_free_roundtrip() -> None:
    handle = _native.call_handle("helm_registry_client_new", None)
    assert handle != 0
    _native.call_status("helm_registry_client_free", _native.HANDLE(handle))


def test_declaration_table_matches_header() -> None:
    """Guard the table against drift when the header sits next to us."""
    header = Path(__file__).resolve().parents[2] / "helm-c" / "include" / "helm_c.h"
    if not header.is_file():
        pytest.skip("helm_c.h not available next to this checkout")

    declared = set(_native.SIGNATURES)
    in_header = set(
        line.split("(")[0].split()[-1].lstrip("*")
        for line in header.read_text().splitlines()
        if line.startswith(("int32_t helm_", "int64_t helm_", "char* helm_", "void helm_"))
    )
    assert in_header <= declared, f"undeclared symbols: {sorted(in_header - declared)}"
