"""Build hook: obtain the native library when the package is built.

Three ways the library gets into the package, in the order they are tried:

1. It is already in ``src/helm_python/lib/`` — what CI does when building
   wheels (``scripts/fetch_native_lib.py --release ...``). Nothing to do.
2. ``HELM_PYTHON_BUILD=1`` is set, or a source build is the only option
   (installing the sdist): compile helm-c-sdk here, after checking that the
   prerequisites exist and reporting precisely what is missing if not.
3. Neither — the build succeeds without a library, and importing the package
   raises an actionable error naming the three ways to supply one. This is
   the normal path when building a pure sdist for later distribution.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess  # nosec B404
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

ROOT = Path(__file__).parent
GO_MOD = "go.mod"
PACKAGE_LIB = ROOT / "src" / "helm_python" / "lib"
LIBRARY_GLOBS = ("libhelm_c.so*", "libhelm_c*.dylib", "libhelm_c*.dll")


def _library_present() -> bool:
    return any(any(PACKAGE_LIB.glob(pattern)) for pattern in LIBRARY_GLOBS)


def _find_source() -> Path | None:
    """Locate a helm-c-sdk source tree to build from."""
    override = os.environ.get("HELM_C_SOURCE")
    if override:
        return Path(override).expanduser().resolve()
    vendored = ROOT / "vendor" / "helm-c"
    if (vendored / GO_MOD).is_file():
        return vendored
    sibling = ROOT.parent / "helm-c"  # development checkout
    if (sibling / GO_MOD).is_file():
        return sibling
    return None


def _required_go_version(source: Path) -> str | None:
    match = re.search(r"^go\s+(\S+)", (source / GO_MOD).read_text(), re.MULTILINE)
    return match.group(1) if match else None


def _preflight(source: Path) -> list[str]:
    """Return a list of problems that would prevent a source build."""
    problems: list[str] = []

    go = shutil.which("go")
    if go is None:
        needed = _required_go_version(source) or "the version in go.mod"
        problems.append(f"Go is not installed (need {needed}+): https://go.dev/dl/")
    else:
        # argv is fixed; `go` was resolved by shutil.which above.
        result = subprocess.run(  # nosec B603
            [go, "version"], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            problems.append(f"`go version` failed: {result.stderr.strip()}")

    if shutil.which("cc") is None and shutil.which("gcc") is None:
        problems.append(
            "no C compiler found (cgo needs one): install build-essential, "
            "Xcode command line tools, or mingw-w64 on Windows"
        )

    if shutil.which("make") is None:
        problems.append("`make` is not installed")

    return problems


def _copy_artifacts(build_dir: Path) -> list[Path]:
    PACKAGE_LIB.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for pattern in LIBRARY_GLOBS:
        for item in sorted(build_dir.glob(pattern)):
            target = PACKAGE_LIB / item.name
            if item.is_symlink():
                target.unlink(missing_ok=True)
                target.symlink_to(os.readlink(item))
            else:
                shutil.copy2(item, target)
            copied.append(target)
    return copied


def build_native_library() -> None:
    """Compile helm-c-sdk and place the result into the package."""
    source = _find_source()
    if source is None:
        raise RuntimeError(
            "HELM_PYTHON_BUILD is set but no helm-c-sdk source was found.\n"
            "Point HELM_C_SOURCE at a checkout, or install from an sdist "
            "(which vendors the source)."
        )

    problems = _preflight(source)
    if problems:
        listed = "\n  - ".join(problems)
        raise RuntimeError(
            "cannot build the native library from source:\n  - "
            f"{listed}\n"
            "Install the missing prerequisites, or use a prebuilt wheel, or "
            "set HELM_C_LIB to a library you built elsewhere."
        )

    # Fixed argv; `make` presence is verified by _preflight above.
    result = subprocess.run(  # nosec B603, B607
        ["make", "build"],
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"building the native library failed:\n{result.stdout}\n{result.stderr}")

    if not _copy_artifacts(source / "build"):
        raise RuntimeError(f"the build produced no library in {source / 'build'}")


class NativeLibraryHook(BuildHookInterface):  # type: ignore[type-arg]
    """Ensures a native library is present before the package is built."""

    PLUGIN_NAME = "helm-native"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if _library_present():
            return
        if os.environ.get("HELM_PYTHON_BUILD") == "1":
            build_native_library()
