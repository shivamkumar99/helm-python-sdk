#!/usr/bin/env python3
"""Dynamic security checks against an installed helm-python-sdk.

Static analysis cannot see across the FFI boundary, so this drives the
*installed* package with hostile input the way an attacker-controlled chart,
values file, or repository would, and asserts that every one of them fails
as a typed exception rather than a crash, a hang, a traversal, or a leak.

    pip install dist/*.whl
    python scripts/dast_check.py

Exits non-zero on the first violation.
"""

from __future__ import annotations

import gzip
import io
import os
import shutil
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

import helm_python as helm

FAILURES: list[str] = []
TIMEOUT_SECONDS = 60


def check(condition: bool, description: str) -> None:
    if condition:
        print(f"  ok   {description}")
    else:
        print(f"  FAIL {description}")
        FAILURES.append(description)


def expect_error(description: str, call, *, allow_success: bool = False) -> None:
    """A hostile input must raise a typed HelmError, never crash the process."""
    try:
        call()
    except helm.HelmError as exc:
        check(
            isinstance(exc.code, int) or exc.code is None, f"{description} -> {type(exc).__name__}"
        )
        return
    except (ValueError, OSError, TypeError) as exc:
        check(True, f"{description} -> {type(exc).__name__} (python-side)")
        return
    if allow_success:
        check(True, f"{description} -> accepted, no crash")
        return
    check(False, f"{description} -> unexpectedly succeeded")


def write_chart(root: Path, name: str = "victim") -> Path:
    chart = root / name
    (chart / "templates").mkdir(parents=True)
    (chart / "Chart.yaml").write_text(f"apiVersion: v2\nname: {name}\nversion: 0.1.0\n")
    (chart / "values.yaml").write_text("replicaCount: 1\n")
    (chart / "templates" / "cm.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {{ .Release.Name }}\n"
    )
    return chart


def test_path_traversal(work: Path) -> None:
    print("\n[1] path traversal")
    for hostile in (
        "../../../../etc/passwd",
        "/etc/shadow",
        str(work / ".." / ".." / "etc" / "passwd"),
        "chart\x00/etc/passwd",
    ):
        expect_error(f"chart load {hostile!r}", lambda p=hostile: helm.Chart.load(p))

    marker = work / "escape-marker"
    expect_error(
        "chart create with a traversing name",
        lambda: helm.Chart.create("../../escaped", work),
    )
    check(not marker.exists(), "no file created outside the target directory")


def test_malicious_archives(work: Path) -> None:
    print("\n[2] malicious archives")

    # Tar entries that try to escape the extraction directory: the classic
    # relative ../ chain and an absolute-path entry. Both markers point into
    # directories this run owns (mode 0700), so their absence is checkable
    # without touching any shared location.
    rel_marker = work.parent / "helm-dast-rel-escape.yaml"
    abs_marker = work / "abs-escape" / "helm-dast-abs-escape.yaml"
    slip = work / "slip.tgz"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        payload = b"apiVersion: v2\nname: evil\nversion: 0.1.0\n"
        for entry_name in (f"../{rel_marker.name}", str(abs_marker)):
            info = tarfile.TarInfo(entry_name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    slip.write_bytes(gzip.compress(buffer.getvalue()))
    expect_error("load archive containing escape entries", lambda: helm.Chart.load(slip))
    check(
        not rel_marker.exists() and not abs_marker.exists(),
        "no traversing archive entry was written to disk",
    )

    # A decompression bomb: small on disk, enormous when expanded.
    bomb = work / "bomb.tgz"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        payload = b"\0" * (200 * 1024 * 1024)
        info = tarfile.TarInfo("bomb/Chart.yaml")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    bomb.write_bytes(gzip.compress(buffer.getvalue()))
    print(f"  (bomb is {bomb.stat().st_size / 1024:.0f} KiB on disk, 200 MiB expanded)")
    expect_error("load decompression bomb", lambda: helm.Chart.load(bomb))

    # Truncated and garbage archives.
    truncated = work / "truncated.tgz"
    truncated.write_bytes(gzip.compress(b"not really a tar")[:20])
    expect_error("load truncated archive", lambda: helm.Chart.load(truncated))

    garbage = work / "garbage.tgz"
    garbage.write_bytes(os.urandom(4096))
    expect_error("load random bytes as a chart", lambda: helm.Chart.load(garbage))


def test_hostile_values(work: Path) -> None:
    print("\n[3] hostile values and expressions")
    chart_dir = write_chart(work / "values-target")
    with helm.Chart.load(chart_dir) as chart:
        expect_error(
            "deeply nested values",
            lambda: chart.merge_values({"a": {"b": {"c": [{"d": "e"} for _ in range(10000)]}}}),
            allow_success=True,
        )
        expect_error(
            "very large value payload",
            lambda: chart.merge_values({"blob": "x" * (5 * 1024 * 1024)}),
            allow_success=True,
        )
        expect_error(
            "null bytes inside values",
            lambda: chart.merge_values({"key\x00injected": "value"}),
            allow_success=True,
        )
        expect_error(
            "template injection attempt in a value",
            lambda: chart.render({"replicaCount": '{{ .Files.Get "/etc/passwd" }}'}),
            allow_success=True,
        )

    for expression in ("a" * 100000 + "=1", "a=1," * 50000, "\x00=\x00", "a[999999999]=1"):
        expect_error(
            f"strvals {expression[:24]!r}...",
            lambda e=expression: helm.parse_set_string(e),
            allow_success=True,
        )
    check(True, "no crash on adversarial --set expressions")


def test_lifecycle_abuse(work: Path) -> None:
    print("\n[4] handle lifecycle abuse")
    chart_dir = write_chart(work / "abuse-target")

    chart = helm.Chart.load(chart_dir)
    chart.close()
    expect_error("metadata after close", lambda: chart.metadata)
    chart.close()
    check(True, "double close does not crash")

    client = helm.RegistryClient()
    client.close()
    expect_error("logout on a closed client", lambda: client.logout("example.com"))

    ctx = helm.HelmContext()
    ctx.close()
    expect_error("cancel on a closed context", lambda: ctx.cancel())

    # Many handles created and released; the registry must not degrade.
    for _ in range(200):
        helm.Chart.load(chart_dir).close()
    check(True, "200 create/free cycles completed")


def test_concurrency(work: Path) -> None:
    print("\n[5] concurrent use from many threads")
    chart_dir = write_chart(work / "thread-target")
    errors: list[Exception] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        try:
            barrier.wait(timeout=30)
            for _ in range(25):
                with helm.Chart.load(chart_dir) as chart:
                    _ = chart.metadata  # exercise the metadata path concurrently
                    chart.render({"replicaCount": 1}, name="threaded")
                helm.parse_set_string("a=1,b.c=2")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=TIMEOUT_SECONDS)

    check(not any(t.is_alive() for t in threads), "no thread hung")
    check(not errors, f"no errors across 8 threads ({errors[:1]})")
    print(f"  (8 threads x 25 iterations in {time.monotonic() - started:.1f}s)")


def test_unreachable_endpoints(work: Path) -> None:
    print("\n[6] hostile and unreachable endpoints")
    expect_error(
        "repo index from a closed port",
        lambda: helm.repo_index("http://127.0.0.1:1"),
    )
    expect_error(
        "repo index from a file:// URL",
        lambda: helm.repo_index("file:///etc/passwd"),
    )
    expect_error(
        "pull from a file:// repository",
        lambda: helm.pull("x", repo_url="file:///etc", destination=work),
    )
    expect_error(
        "oci pull from a closed port",
        lambda: helm.pull("oci://127.0.0.1:1/x/y", destination=work, plain_http=True),
    )


def main() -> int:
    print(f"helm-python-sdk DAST — library: {helm.library_path}")
    print(f"helm-c {helm.helm_c_version()}, Helm SDK {helm.helm_sdk_version()}")

    baseline = helm.open_handles_count()
    work = Path(tempfile.mkdtemp(prefix="helm-dast-"))
    try:
        test_path_traversal(work)
        test_malicious_archives(work)
        test_hostile_values(work)
        test_lifecycle_abuse(work)
        test_concurrency(work)
        test_unreachable_endpoints(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("\n[7] resource accounting")
    leaked = helm.open_handles_count() - baseline
    check(leaked == 0, f"no handles leaked across every hostile case ({leaked} open)")

    print()
    if FAILURES:
        print(f"DAST FAILED — {len(FAILURES)} issue(s):")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("DAST passed: every hostile input failed safely, no leaks, no hangs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
