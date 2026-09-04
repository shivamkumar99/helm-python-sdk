#!/usr/bin/env python3
"""Retag a built wheel as platform-specific.

The wheel bundles a native library, so it must NOT be published as
``py3-none-any`` — pip would install a macOS dylib on Linux. The build
backend produces a pure-Python tag, so CI runs this immediately afterwards
to stamp the platform it was actually built on.

    python -m build --wheel
    python scripts/tag_wheel.py dist/*.whl
"""

from __future__ import annotations

import argparse
import subprocess  # nosec B404
import sys
import zipfile
from pathlib import Path

from packaging.tags import sys_tags

LIBRARY_MARKERS = ("helm_python/lib/libhelm_c",)


def assert_bundles_library(wheel: Path) -> None:
    """Refuse to platform-tag a wheel that carries no native library.

    ``python -m build`` (both targets) builds the wheel *from the sdist*,
    which excludes the library directory — producing a wheel that imports
    nothing. Metadata checks like ``twine check`` do not look inside, so
    this is the gate that catches it. Build wheels with
    ``python -m build --wheel`` so they come from the source tree.
    """
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    if not any(name.startswith(LIBRARY_MARKERS) for name in names):
        raise SystemExit(
            f"{wheel.name} contains no native library, so it would fail to "
            "import once installed.\n"
            "Populate it first (scripts/fetch_native_lib.py) and build with "
            "`python -m build --wheel`, which builds from the source tree "
            "rather than from the sdist."
        )


def platform_tag() -> str:
    """The most specific platform tag for the interpreter running this."""
    for tag in sys_tags():
        if tag.platform != "any":
            return str(tag.platform)
    raise SystemExit("could not determine a platform tag for this interpreter")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path, help="the wheel to retag, in place")
    parser.add_argument(
        "--platform-tag",
        default=None,
        help="override the detected platform tag (e.g. manylinux_2_28_x86_64)",
    )
    args = parser.parse_args()

    if not args.wheel.is_file():
        raise SystemExit(f"no such wheel: {args.wheel}")

    assert_bundles_library(args.wheel)

    tag = args.platform_tag or platform_tag()
    # argv is fixed and runs this same interpreter.
    result = subprocess.run(  # nosec B603
        [
            sys.executable,
            "-m",
            "wheel",
            "tags",
            "--platform-tag",
            tag,
            "--remove",
            str(args.wheel),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"retagging failed: {result.stderr.strip()}")

    print(result.stdout.strip() or f"retagged with {tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
