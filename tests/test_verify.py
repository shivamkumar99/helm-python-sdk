"""Provenance verification against generated signing material.

The fixtures (signed chart + .prov + public keyring) are produced by
helm-c-sdk's generator, so nothing is committed here either.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import helm_python as helm

HELM_C = Path(__file__).resolve().parents[2] / "helm-c"


@pytest.fixture(scope="session")
def signing_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a signed chart, its provenance file, and a public keyring."""
    if not (HELM_C / "test" / "genfixtures").is_dir():
        pytest.skip("helm-c-sdk checkout not available")
    go_binary = shutil.which("go")
    if go_binary is None:
        pytest.skip("Go toolchain not available to generate signing fixtures")

    out = tmp_path_factory.mktemp("signing")
    result = subprocess.run(  # fixed argv, resolved binary, no shell
        [go_binary, "run", "./test/genfixtures", "-dir", str(out)],
        cwd=HELM_C,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"could not generate signing fixtures: {result.stderr.strip()}")
    return out


def test_verify_signed_chart(signing_dir: Path) -> None:
    result = helm.verify(
        signing_dir / "testchart-0.1.0.tgz",
        signing_dir / "pubring.gpg",
    )
    assert result["file_name"] == "testchart-0.1.0.tgz"
    assert result["file_hash"].startswith("sha256:")
    assert result["signed_by"], "the signer identity is reported"


def test_verify_explicit_provenance_file(signing_dir: Path) -> None:
    result = helm.verify(
        signing_dir / "testchart-0.1.0.tgz",
        signing_dir / "pubring.gpg",
        provenance_file=signing_dir / "testchart-0.1.0.tgz.prov",
    )
    assert result["file_name"] == "testchart-0.1.0.tgz"


def test_verify_unsigned_chart_fails(signing_dir: Path, tmp_path: Path) -> None:
    unsigned = tmp_path / "unsigned"
    unsigned.mkdir()
    with helm.Chart.create("unsignedchart", unsigned) as chart:
        archive = chart.save(unsigned)

    with pytest.raises(helm.HelmChartInvalidError):
        helm.verify(archive, signing_dir / "pubring.gpg")


def test_verify_missing_chart_fails(signing_dir: Path) -> None:
    with pytest.raises(helm.HelmChartInvalidError):
        helm.verify(signing_dir / "no-such-chart.tgz", signing_dir / "pubring.gpg")
