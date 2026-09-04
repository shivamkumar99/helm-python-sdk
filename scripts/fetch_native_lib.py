#!/usr/bin/env python3
"""Place the native library into the package so a wheel can ship it.

Two sources, matching the acquisition ladder in PLAN.md:

    # from a local helm-c-sdk build (development, air-gapped, exotic arches)
    python scripts/fetch_native_lib.py --from-dir ../helm-c/build

    # from a helm-c-sdk GitHub release (what CI does when building wheels)
    python scripts/fetch_native_lib.py --release v0.1.0

Release downloads are verified against the release's ``sha256sums.txt``
before anything is unpacked, and the archive's own checksum file is the only
trust anchor used.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

REPO = "shivamkumar99/helm-c-sdk"
PACKAGE_LIB = Path(__file__).resolve().parents[1] / "src" / "helm_python" / "lib"

# Release asset naming: helm-c-<version>-<platform>.tar.gz
PLATFORMS = {
    ("linux", "x86_64"): "linux-amd64",
    ("linux", "aarch64"): "linux-arm64",
    ("darwin", "arm64"): "darwin-arm64",
    ("darwin", "x86_64"): "darwin-amd64",
    ("win32", "amd64"): "windows-amd64",
}

LIBRARY_GLOBS = ("libhelm_c.so*", "libhelm_c*.dylib", "libhelm_c*.dll")


def platform_tag() -> str:
    machine = os.uname().machine if hasattr(os, "uname") else "amd64"
    key = (sys.platform, machine.lower())
    if key not in PLATFORMS:
        raise SystemExit(
            f"no prebuilt library for {key}. Build helm-c-sdk from source "
            "(make build) and use --from-dir, or install with "
            "HELM_PYTHON_BUILD=1."
        )
    return PLATFORMS[key]


def copy_from_dir(source: Path) -> list[Path]:
    """Copy library files (and their symlinks) out of a build directory."""
    copied: list[Path] = []
    PACKAGE_LIB.mkdir(parents=True, exist_ok=True)
    for pattern in LIBRARY_GLOBS:
        for item in sorted(source.glob(pattern)):
            target = PACKAGE_LIB / item.name
            if item.is_symlink():
                target.unlink(missing_ok=True)
                target.symlink_to(os.readlink(item))
            else:
                shutil.copy2(item, target)
            copied.append(target)
    if not copied:
        raise SystemExit(f"no helm-c library found in {source}")
    return copied


def _download(url: str, destination: Path, token: str | None) -> None:
    if not url.startswith("https://"):
        raise SystemExit(f"refusing to download over a non-HTTPS URL: {url}")
    # The scheme is checked immediately above.
    request = urllib.request.Request(url)  # nosec B310
    request.add_header("Accept", "application/octet-stream")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        # https is enforced above.
        with urllib.request.urlopen(request) as response:  # nosec B310
            destination.write_bytes(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise SystemExit(
                f"could not download {url} (HTTP {exc.code}).\n"
                "If shivamkumar99/helm-c-sdk is private, set GITHUB_TOKEN to a "
                "token that can read it; if it is public, check that the release "
                "and its platform asset exist."
            ) from exc
        raise


def fetch_release(version: str) -> list[Path]:
    """Download, verify, and unpack the release asset for this platform."""
    tag = platform_tag()
    archive_name = f"helm-c-{version}-{tag}.tar.gz"
    base = f"https://github.com/{REPO}/releases/download/{version}"
    token = os.environ.get("GITHUB_TOKEN")

    with tempfile.TemporaryDirectory() as work_dir:
        work = Path(work_dir)
        archive = work / archive_name
        sums = work / "sha256sums.txt"
        _download(f"{base}/{archive_name}", archive, token)
        _download(f"{base}/sha256sums.txt", sums, token)

        expected = {
            parts[1].lstrip("*"): parts[0]
            for line in sums.read_text().splitlines()
            if (parts := line.split()) and len(parts) >= 2
        }
        if archive_name not in expected:
            raise SystemExit(f"{archive_name} is not listed in sha256sums.txt")

        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != expected[archive_name]:
            raise SystemExit(
                f"checksum mismatch for {archive_name}:\n"
                f"  expected {expected[archive_name]}\n"
                f"  actual   {digest}"
            )

        with tarfile.open(archive) as tar:
            tar.extractall(work / "unpacked", filter="data")
        unpacked = next((work / "unpacked").iterdir())
        return copy_from_dir(unpacked)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-dir", type=Path, help="a local helm-c-sdk build/ directory")
    group.add_argument("--release", help="a helm-c-sdk release tag, e.g. v0.1.0")
    args = parser.parse_args()

    copied = copy_from_dir(args.from_dir) if args.from_dir else fetch_release(args.release)
    for path in copied:
        print(f"placed {path.relative_to(PACKAGE_LIB.parents[2])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
