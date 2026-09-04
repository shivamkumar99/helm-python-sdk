#!/usr/bin/env python3
"""Vendor the helm-c-sdk source into ``vendor/helm-c`` for the sdist.

The sdist must be self-contained: installing it on a platform without a
wheel compiles the native library locally, and doing that from a vendored
snapshot means no unpinned code is fetched at install time.

    python scripts/vendor_helm_c.py --from-dir ../helm-c

Only files tracked by git are copied (no build output, no local state).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess  # nosec B404
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "helm-c"


def vendor(source: Path) -> int:
    if not (source / "go.mod").is_file():
        raise SystemExit(f"{source} does not look like a helm-c-sdk checkout")

    # Fixed argv, no shell.
    result = subprocess.run(  # nosec B603, B607
        ["git", "ls-files"],
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"could not list tracked files in {source}")

    tracked = [line for line in result.stdout.splitlines() if line]
    if VENDOR.exists():
        shutil.rmtree(VENDOR)

    for relative in tracked:
        src = source / relative
        if not src.is_file():
            continue
        dst = VENDOR / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    print(f"vendored {len(tracked)} files into {VENDOR}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-dir",
        type=Path,
        required=True,
        help="a helm-c-sdk checkout at the pinned release tag",
    )
    args = parser.parse_args()
    return vendor(args.from_dir.expanduser().resolve())


if __name__ == "__main__":
    raise SystemExit(main())
