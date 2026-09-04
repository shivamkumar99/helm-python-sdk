"""Chart operations against the real native library."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import helm_python as helm

CHART_YAML = """apiVersion: v2
name: sample
description: Generated test chart
type: application
version: 0.1.0
appVersion: "1.0.0"
"""

VALUES_YAML = """replicaCount: 1
image:
  repository: nginx
  tag: stable
"""

TEMPLATE = """apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Release.Name }}-config
data:
  replicas: {{ .Values.replicaCount | quote }}
  image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
  namespace: {{ .Release.Namespace }}
"""

SCHEMA = json.dumps(
    {
        "$schema": "https://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {"replicaCount": {"type": "integer", "minimum": 0}},
        "required": ["replicaCount"],
    }
)


def _write_chart(root: Path, *, with_schema: bool = False) -> Path:
    """Create a minimal chart on disk; fixtures are generated, never committed."""
    chart_dir = root / "sample"
    (chart_dir / "templates").mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(CHART_YAML)
    (chart_dir / "values.yaml").write_text(VALUES_YAML)
    (chart_dir / "templates" / "configmap.yaml").write_text(TEMPLATE)
    if with_schema:
        (chart_dir / "values.schema.json").write_text(SCHEMA)
    return chart_dir


@pytest.fixture
def chart_dir(tmp_path: Path) -> Path:
    return _write_chart(tmp_path)


@pytest.fixture
def chart(chart_dir: Path):
    with helm.Chart.load(chart_dir) as loaded:
        yield loaded


# --- loading and lifecycle ------------------------------------------------


def test_load_and_inspect(chart: helm.Chart) -> None:
    assert chart.name == "sample"
    assert chart.version == "0.1.0"
    assert chart.metadata["appVersion"] == "1.0.0"
    assert chart.values["replicaCount"] == 1


def test_load_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(helm.HelmChartLoadError):
        helm.Chart.load(tmp_path / "nope")


def test_context_manager_closes(chart_dir: Path) -> None:
    with helm.Chart.load(chart_dir) as chart:
        assert not chart.closed
    assert chart.closed


def test_close_is_idempotent(chart_dir: Path) -> None:
    chart = helm.Chart.load(chart_dir)
    chart.close()
    chart.close()  # must not raise
    assert chart.closed


def test_use_after_close_raises(chart_dir: Path) -> None:
    chart = helm.Chart.load(chart_dir)
    chart.close()
    with pytest.raises(helm.HelmError):
        _ = chart.metadata


def test_garbage_collection_frees_the_handle(chart_dir: Path) -> None:
    """A forgotten chart must not leak — the finalizer is the safety net."""
    import gc

    before = helm.open_handles_count()
    helm.Chart.load(chart_dir)  # deliberately not stored
    gc.collect()
    assert helm.open_handles_count() == before


def test_repr_mentions_state(chart_dir: Path) -> None:
    chart = helm.Chart.load(chart_dir)
    assert "Chart" in repr(chart)
    chart.close()
    assert "closed" in repr(chart)


def test_accepts_pathlib_and_str(chart_dir: Path) -> None:
    with helm.Chart.load(chart_dir) as from_path:
        assert from_path.name == "sample"
    with helm.Chart.load(str(chart_dir)) as from_str:
        assert from_str.name == "sample"


# --- creating, saving, packaging ------------------------------------------


def test_create_scaffold(tmp_path: Path) -> None:
    with helm.Chart.create("newchart", tmp_path) as chart:
        assert chart.name == "newchart"
    assert (tmp_path / "newchart" / "Chart.yaml").is_file()


def test_create_rejects_invalid_name(tmp_path: Path) -> None:
    with pytest.raises(helm.HelmInvalidArgError):
        helm.Chart.create("Bad Name!", tmp_path)


def test_save_roundtrip(chart: helm.Chart, tmp_path: Path) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    archive = chart.save(dest)
    assert archive.endswith("sample-0.1.0.tgz")
    assert Path(archive).is_file()

    with helm.Chart.load(archive) as reloaded:
        assert reloaded.name == "sample"


def test_package(chart_dir: Path, tmp_path: Path) -> None:
    dest = tmp_path / "pkg"
    dest.mkdir()
    archive = helm.package(chart_dir, destination=dest)
    assert Path(archive).is_file()

    versioned = helm.package(chart_dir, destination=dest, version="9.9.9")
    assert "9.9.9" in versioned


def test_package_rejects_unknown_option(chart_dir: Path) -> None:
    with pytest.raises(helm.HelmChartInvalidError):
        helm.package(chart_dir / "does-not-exist")


# --- values, schema, rendering --------------------------------------------


def test_merge_values(chart: helm.Chart) -> None:
    assert chart.merge_values()["replicaCount"] == 1
    merged = chart.merge_values({"replicaCount": 5})
    assert merged["replicaCount"] == 5
    assert merged["image"]["repository"] == "nginx", "siblings survive the merge"


def test_validate_schema_without_schema_always_passes(chart: helm.Chart) -> None:
    chart.validate_schema({"anything": "goes"})


def test_validate_schema_enforced_when_present(tmp_path: Path) -> None:
    chart_dir = _write_chart(tmp_path, with_schema=True)
    with helm.Chart.load(chart_dir) as chart:
        chart.validate_schema({"replicaCount": 3})
        with pytest.raises(helm.HelmValuesError):
            chart.validate_schema({"replicaCount": -1})


def test_render_defaults(chart: helm.Chart) -> None:
    manifests = chart.render()
    assert "sample/templates/configmap.yaml" in manifests
    body = manifests["sample/templates/configmap.yaml"]
    assert 'replicas: "1"' in body
    assert "release-name-config" in body, "default release name applied"


def test_render_with_values_and_options(chart: helm.Chart) -> None:
    manifests = chart.render(
        values={"replicaCount": 4},
        name="demo",
        namespace="prod",
        revision=2,
        is_upgrade=True,
    )
    body = manifests["sample/templates/configmap.yaml"]
    assert 'replicas: "4"' in body
    assert "demo-config" in body
    assert "namespace: prod" in body


def test_render_failure(tmp_path: Path) -> None:
    chart_dir = _write_chart(tmp_path)
    (chart_dir / "templates" / "broken.yaml").write_text('{{ fail "boom" }}\n')
    with helm.Chart.load(chart_dir) as chart, pytest.raises(helm.HelmRenderError):
        chart.render()


# --- lint -----------------------------------------------------------------


def test_lint_clean_chart(chart_dir: Path) -> None:
    report = helm.lint(chart_dir)
    assert report["total_charts_linted"] == 1
    assert report["errors"] == []


def test_lint_findings_are_data_not_exceptions(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "Chart.yaml").write_text("not: a valid chart\n")
    report = helm.lint(broken)
    assert report["errors"] or report["messages"], "problems reported in the payload"


def test_non_serializable_values_fail_in_python(chart_dir: Path) -> None:
    """Values are serialized by us, so bad input fails before the boundary."""
    with pytest.raises(TypeError):
        helm.lint(chart_dir, {"ok": object})  # type: ignore[dict-item]
