"""Show, repository index generation, and OCI queries."""

from __future__ import annotations

from pathlib import Path

import pytest

import helm_python as helm

from .test_chart import _write_chart


@pytest.fixture
def chart_dir(tmp_path: Path) -> Path:
    return _write_chart(tmp_path)


@pytest.fixture
def chart(chart_dir: Path):
    with helm.Chart.load(chart_dir) as loaded:
        yield loaded


def test_show_local_chart_values(chart_dir: Path) -> None:
    text = helm.show(str(chart_dir), format="values")
    assert "replicaCount" in text


def test_show_all_includes_the_definition(chart_dir: Path) -> None:
    text = helm.show(str(chart_dir))
    assert "apiVersion: v2" in text


def test_show_unknown_format_raises(chart_dir: Path) -> None:
    with pytest.raises(helm.HelmError):
        helm.show(str(chart_dir), format="bogus")


def test_repo_index_generate(chart: helm.Chart, tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    chart.save(repo_dir)

    index = helm.repo_index_generate(repo_dir, base_url="https://charts.example.com")
    assert (repo_dir / "index.yaml").is_file()
    entries = index["entries"]
    assert chart.name in entries
    assert entries[chart.name][0]["urls"][0].startswith("https://charts.example.com")


def test_repo_index_generate_json(chart: helm.Chart, tmp_path: Path) -> None:
    repo_dir = tmp_path / "repo-json"
    repo_dir.mkdir()
    chart.save(repo_dir)
    helm.repo_index_generate(repo_dir, json_index=True)
    assert (repo_dir / "index.json").is_file()


def test_registry_tags_unreachable_host_raises() -> None:
    with helm.RegistryClient(plain_http=True) as client, pytest.raises(helm.HelmError):
        client.tags("oci://127.0.0.1:1/charts/anything")


def test_registry_resolve_unreachable_host_raises() -> None:
    with helm.RegistryClient(plain_http=True) as client, pytest.raises(helm.HelmError):
        client.resolve("oci://127.0.0.1:1/charts/anything:1.0.0")
