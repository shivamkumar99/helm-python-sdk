"""Full release lifecycle against a real cluster.

Skipped automatically when no cluster is reachable, so the default test run
stays hermetic. CI runs these against a kind cluster; locally they pick up
whatever ``kubectl`` context you have.

    pytest -m cluster
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

import pytest

import helm_python as helm

from .test_chart import _write_chart

pytestmark = pytest.mark.cluster

RELEASE = "helm-python-e2e"


@pytest.fixture(scope="module")
def cluster_config() -> Iterator[helm.Config]:
    """A config bound to a reachable cluster, or skip the module."""
    cfg = helm.Config(namespace="default")
    try:
        cfg.list()
    except helm.HelmError as exc:
        cfg.close()
        pytest.skip(f"no reachable cluster: {exc}")
    try:
        yield cfg
    finally:
        cfg.close()


@pytest.fixture(scope="module")
def chart_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _write_chart(tmp_path_factory.mktemp("chart"))


@pytest.fixture(autouse=True)
def _cleanup(cluster_config: helm.Config) -> Iterator[None]:
    """Leave no release behind, even if a test fails midway."""
    yield
    with contextlib.suppress(helm.HelmError):
        cluster_config.uninstall(RELEASE, ignore_not_found=True)


def test_release_lifecycle(cluster_config: helm.Config, chart_dir: Path) -> None:
    cfg = cluster_config

    # Install revision 1.
    release = cfg.install(chart_dir, RELEASE, {"replicaCount": 2}, wait="watcher", timeout=120)
    assert release["name"] == RELEASE
    assert release["revision"] == 1
    assert release["status"] == "deployed"
    assert 'replicas: "2"' in release["manifest"]

    # It shows up in listings and status.
    assert any(item["name"] == RELEASE for item in cfg.list())
    assert cfg.status(RELEASE)["revision"] == 1

    # Upgrade to revision 2.
    upgraded = cfg.upgrade(chart_dir, RELEASE, {"replicaCount": 3}, wait="watcher", timeout=120)
    assert upgraded["revision"] == 2
    assert 'replicas: "3"' in upgraded["manifest"]

    # User-supplied values round-trip; history records both revisions.
    assert cfg.get_values(RELEASE) == {"replicaCount": 3}
    assert len(cfg.history(RELEASE)) == 2
    assert cfg.get_metadata(RELEASE)["chart"] == "sample"

    # Roll back to revision 1, which creates revision 3.
    cfg.rollback(RELEASE, version=1, timeout=120)
    rolled_back = cfg.status(RELEASE)
    assert rolled_back["revision"] == 3
    assert 'replicas: "2"' in rolled_back["manifest"]

    # Uninstall.
    result = cfg.uninstall(RELEASE, timeout=120)
    assert "uninstalled" in str(result).lower()
    assert not any(item["name"] == RELEASE for item in cfg.list())


def test_install_with_loaded_chart(cluster_config: helm.Config, chart_dir: Path) -> None:
    with helm.Chart.load(chart_dir) as chart:
        release = cluster_config.install(chart, RELEASE, timeout=120)
        assert release["status"] == "deployed"


def test_dry_run_does_not_persist(cluster_config: helm.Config, chart_dir: Path) -> None:
    release = cluster_config.install(chart_dir, RELEASE, dry_run="client")
    assert release["status"] == "pending-install"
    assert not any(item["name"] == RELEASE for item in cluster_config.list(all=True))


def test_status_of_missing_release(cluster_config: helm.Config) -> None:
    with pytest.raises(helm.HelmNotFoundError):
        cluster_config.status("definitely-not-installed")


def test_uninstall_ignore_not_found(cluster_config: helm.Config) -> None:
    cluster_config.uninstall("definitely-not-installed", ignore_not_found=True)
