"""The build hook that supplies the native library.

The hook itself is exercised for real by the wheel builds in CI; these tests
cover its decision logic and — most importantly — that a missing
prerequisite produces an actionable message rather than a confusing
compiler error.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

hatch_build = pytest.importorskip("hatch_build", reason="hatchling is only needed when building")


def test_finds_an_explicit_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example\n\ngo 1.26.0\n")
    monkeypatch.setenv("HELM_C_SOURCE", str(tmp_path))
    assert hatch_build._find_source() == tmp_path.resolve()


def test_reports_every_missing_prerequisite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "go.mod").write_text("module example\n\ngo 1.26.0\n")
    monkeypatch.setattr(hatch_build.shutil, "which", lambda _name: None)

    problems = hatch_build._preflight(tmp_path)

    joined = " ".join(problems)
    assert "Go is not installed" in joined
    assert "1.26.0" in joined, "the required Go version comes from go.mod"
    assert "C compiler" in joined
    assert "make" in joined


def test_preflight_passes_on_a_normal_developer_machine(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example\n\ngo 1.26.0\n")
    if hatch_build.shutil.which("go") is None:
        pytest.skip("Go is not installed here")
    assert hatch_build._preflight(tmp_path) == []


def test_build_without_source_explains_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HELM_C_SOURCE", raising=False)
    monkeypatch.setattr(hatch_build, "_find_source", lambda: None)

    with pytest.raises(RuntimeError) as excinfo:
        hatch_build.build_native_library()
    assert "HELM_C_SOURCE" in str(excinfo.value)


def test_missing_prerequisites_abort_the_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "go.mod").write_text("module example\n\ngo 1.26.0\n")
    monkeypatch.setattr(hatch_build, "_find_source", lambda: tmp_path)
    monkeypatch.setattr(hatch_build, "_preflight", lambda _source: ["Go is not installed"])

    with pytest.raises(RuntimeError) as excinfo:
        hatch_build.build_native_library()
    message = str(excinfo.value)
    assert "Go is not installed" in message
    assert "HELM_C_LIB" in message, "the message offers the other ways out"


def test_hook_is_a_noop_when_the_library_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hatch_build, "_library_present", lambda: True)
    monkeypatch.setattr(
        hatch_build,
        "build_native_library",
        lambda: pytest.fail("must not rebuild when a library is already present"),
    )
    hook = hatch_build.NativeLibraryHook.__new__(hatch_build.NativeLibraryHook)
    build_data: dict[str, Any] = {}
    hook.initialize("standard", build_data)


def test_hook_does_nothing_without_the_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plain sdist build must not try to compile anything."""
    monkeypatch.setattr(hatch_build, "_library_present", lambda: False)
    monkeypatch.delenv("HELM_PYTHON_BUILD", raising=False)
    monkeypatch.setattr(
        hatch_build,
        "build_native_library",
        lambda: pytest.fail("must not build without HELM_PYTHON_BUILD=1"),
    )
    hook = hatch_build.NativeLibraryHook.__new__(hatch_build.NativeLibraryHook)
    hook.initialize("standard", {})


def test_the_package_declares_no_runtime_dependencies() -> None:
    """A pip install must pull in nothing but this package.

    Zero runtime dependencies is a deliberate supply-chain property — ctypes
    is stdlib and the native library ships inside the wheel — so a new
    dependency has to be a conscious decision, made here first.
    """
    tomllib = pytest.importorskip("tomllib", reason="tomllib is stdlib from 3.11")

    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert metadata["project"]["dependencies"] == []
