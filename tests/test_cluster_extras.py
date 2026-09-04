"""Cluster-side additions: reachability, registry binding, queries, render.

Everything here runs without a cluster: the shared ``config`` fixture points
at an unreachable API server, so cluster-touching calls must fail as typed
errors, while calls that only need the configuration succeed.
"""

from __future__ import annotations

import pytest

import helm_python as helm

from .test_chart import _write_chart
from .test_config import UNREACHABLE_KUBECONFIG


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "kubeconfig.yaml"
    path.write_text(UNREACHABLE_KUBECONFIG)
    with helm.Config(kubeconfig_path=path, storage_driver="memory") as cfg:
        yield cfg


@pytest.fixture
def chart(tmp_path):
    with helm.Chart.load(_write_chart(tmp_path)) as loaded:
        yield loaded


def test_check_reachable_unreachable_cluster(config: helm.Config) -> None:
    with pytest.raises(helm.HelmKubeError):
        config.check_reachable()


def test_set_registry_client_bind_and_unbind(config: helm.Config) -> None:
    with helm.RegistryClient() as client:
        config.set_registry_client(client)
        config.set_registry_client(None)


def test_set_registry_client_rejects_closed_client(config: helm.Config) -> None:
    client = helm.RegistryClient()
    client.close()
    with pytest.raises(helm.HelmError):
        config.set_registry_client(client)


def test_get_all_unreachable_cluster(config: helm.Config) -> None:
    with pytest.raises(helm.HelmKubeError):
        config.get_all("anything")


def test_test_unreachable_cluster(config: helm.Config) -> None:
    with pytest.raises(helm.HelmKubeError):
        config.test("anything", timeout=1)


def test_render_without_lookup_works_offline(config: helm.Config, chart: helm.Chart) -> None:
    # Cluster-aware render only contacts the API server when a template
    # calls `lookup`; this chart never does, so it renders even though the
    # cluster is unreachable.
    manifests = config.render(chart, {"replicaCount": 2}, name="offline-render")
    assert any("offline-render" in body for body in manifests.values())
