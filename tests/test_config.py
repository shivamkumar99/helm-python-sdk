"""Cluster configuration, cancellation, and release-action plumbing.

These tests need no cluster: they cover configuration, lifecycles, argument
handling, and the failure paths every action takes when the cluster is
unreachable. The full release lifecycle against a live cluster lives in
``test_cluster.py``.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

import helm_python as helm

from .test_chart import _write_chart

UNREACHABLE_KUBECONFIG = """apiVersion: v1
kind: Config
clusters:
  - name: nowhere
    cluster:
      server: https://127.0.0.1:1
contexts:
  - name: nowhere
    context:
      cluster: nowhere
      user: nobody
current-context: nowhere
users:
  - name: nobody
    user: {}
"""


@pytest.fixture
def kubeconfig(tmp_path: Path) -> Path:
    path = tmp_path / "kubeconfig.yaml"
    path.write_text(UNREACHABLE_KUBECONFIG)
    return path


@pytest.fixture
def config(kubeconfig: Path):
    with helm.Config(kubeconfig_path=kubeconfig, storage_driver="memory") as cfg:
        yield cfg


@pytest.fixture
def chart(tmp_path: Path):
    with helm.Chart.load(_write_chart(tmp_path)) as loaded:
        yield loaded


# --- configuration --------------------------------------------------------


def test_config_lifecycle(kubeconfig: Path) -> None:
    cfg = helm.Config(kubeconfig_path=kubeconfig)
    assert not cfg.closed
    cfg.close()
    assert cfg.closed
    cfg.close()  # idempotent


def test_config_from_inline_kubeconfig() -> None:
    """Inline content avoids writing a kubeconfig yourself."""
    with helm.Config(kubeconfig_content=UNREACHABLE_KUBECONFIG, storage_driver="memory") as cfg:
        assert not cfg.closed


def test_config_rejects_both_kubeconfig_forms(kubeconfig: Path) -> None:
    with pytest.raises(helm.HelmInvalidArgError):
        helm.Config(kubeconfig_path=kubeconfig, kubeconfig_content=UNREACHABLE_KUBECONFIG)


def test_config_accepts_the_full_kube_surface(kubeconfig: Path) -> None:
    with helm.Config(
        kubeconfig_path=kubeconfig,
        kube_context="nowhere",
        kube_token="stub-bearer-value-for-signature-test",
        kube_apiserver="https://127.0.0.1:1",
        kube_tls_server_name="api.internal",
        kube_insecure_skip_tls_verify=True,
        kube_as_user="alice",
        kube_as_groups=["dev", "ops"],
        burst_limit=50,
        qps=25.5,
        namespace="testing",
        storage_driver="memory",
    ) as cfg:
        assert not cfg.closed


def test_config_creation_does_not_contact_the_cluster(kubeconfig: Path) -> None:
    """Construction is lazy; connection errors appear on the first action."""
    with helm.Config(kubeconfig_path=kubeconfig, storage_driver="memory") as cfg:
        assert not cfg.closed  # unreachable server, but no error yet


def test_closed_config_rejects_use(kubeconfig: Path) -> None:
    cfg = helm.Config(kubeconfig_path=kubeconfig)
    cfg.close()
    with pytest.raises(helm.HelmError):
        cfg.list()


# --- cancellation contexts ------------------------------------------------


def test_context_lifecycle() -> None:
    ctx = helm.HelmContext()
    assert not ctx.closed
    ctx.cancel()
    ctx.cancel()  # repeatable
    ctx.close()
    assert ctx.closed
    ctx.close()  # idempotent


def test_context_as_context_manager() -> None:
    with helm.HelmContext() as ctx:
        ctx.cancel()
    assert ctx.closed


def test_context_cancel_from_another_thread() -> None:
    ctx = helm.HelmContext()
    done = threading.Event()

    def cancel() -> None:
        ctx.cancel()
        done.set()

    thread = threading.Thread(target=cancel)
    thread.start()
    thread.join(timeout=5)
    assert done.is_set(), "cancel must be callable from any thread"
    ctx.close()


def test_cancelled_context_aborts_install(config: helm.Config, chart: helm.Chart) -> None:
    with helm.HelmContext() as ctx:
        ctx.cancel()
        with pytest.raises(helm.HelmCancelledError):
            config.install(chart, "cancelled-release", context=ctx)


# --- actions against an unreachable cluster -------------------------------


def test_read_actions_fail_cleanly(config: helm.Config) -> None:
    """Every action checks reachability first: a clean error, never a hang."""
    for call in (
        lambda: config.list(),
        lambda: config.status("absent"),
        lambda: config.history("absent"),
        lambda: config.get_values("absent"),
        lambda: config.get_metadata("absent"),
    ):
        with pytest.raises(helm.HelmError):
            call()


def test_write_actions_fail_cleanly(config: helm.Config, chart: helm.Chart) -> None:
    with pytest.raises(helm.HelmError):
        config.install(chart, "some-release")
    with pytest.raises(helm.HelmError):
        config.upgrade(chart, "some-release")
    with pytest.raises(helm.HelmError):
        config.uninstall("some-release")
    with pytest.raises(helm.HelmError):
        config.rollback("some-release")


def test_install_accepts_a_chart_reference(config: helm.Config, tmp_path: Path) -> None:
    """A path works in place of a loaded chart; the chart still resolves."""
    chart_dir = _write_chart(tmp_path)
    with pytest.raises(helm.HelmError) as excinfo:
        config.install(chart_dir, "ref-release")
    # It failed at the cluster, not while resolving the chart.
    assert "unreachable" in str(excinfo.value).lower()


def test_install_with_missing_chart_reference(config: helm.Config, tmp_path: Path) -> None:
    with pytest.raises(helm.HelmChartLoadError):
        config.install(tmp_path / "no-such-chart", "bad-release")


def test_options_are_validated_before_the_cluster(config: helm.Config, chart: helm.Chart) -> None:
    """A bogus wait strategy is rejected without a round trip."""
    with pytest.raises(helm.HelmError):
        config.install(chart, "opts-release", wait="not-a-strategy")
