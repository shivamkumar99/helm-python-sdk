"""Chart content access, in-memory archives, and offline chart utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

import helm_python as helm

from .test_chart import _write_chart


@pytest.fixture
def chart_dir(tmp_path: Path) -> Path:
    return _write_chart(tmp_path / "plain")


@pytest.fixture
def chart(chart_dir: Path):
    with helm.Chart.load(chart_dir) as loaded:
        yield loaded


def _chart_with_extras(root: Path) -> Path:
    """A chart carrying files, a CRD, a schema, and a declared dependency."""
    chart = root / "extras"
    (chart / "templates").mkdir(parents=True)
    (chart / "crds").mkdir()
    (chart / "Chart.yaml").write_text(
        "apiVersion: v2\n"
        "name: extras\n"
        "version: 1.2.3\n"
        "dependencies:\n"
        "  - name: absent\n"
        "    version: 9.9.9\n"
        '    repository: "https://charts.invalid"\n'
    )
    (chart / "values.yaml").write_text("replicaCount: 1\n")
    (chart / "values.schema.json").write_text(
        '{"$schema": "https://json-schema.org/draft-07/schema#", "type": "object"}'
    )
    (chart / "README.md").write_text("# extras\n")
    (chart / "templates" / "cm.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: {{ .Release.Name }}\n"
    )
    (chart / "crds" / "widgets.yaml").write_text(
        "apiVersion: apiextensions.k8s.io/v1\nkind: CustomResourceDefinition\n"
        "metadata:\n  name: widgets.example.com\n"
    )
    return chart


@pytest.fixture
def extras_dir(tmp_path: Path) -> Path:
    return _chart_with_extras(tmp_path)


@pytest.fixture
def extras(extras_dir: Path):
    with helm.Chart.load(extras_dir) as loaded:
        yield loaded


def test_files_lists_non_template_files(extras: helm.Chart) -> None:
    names = {f["name"] for f in extras.files}
    assert "README.md" in names
    readme = next(f for f in extras.files if f["name"] == "README.md")
    assert "# extras" in readme["data"]


def test_templates_carry_raw_sources(extras: helm.Chart) -> None:
    templates = extras.templates
    assert any(t["name"].endswith("cm.yaml") for t in templates)
    source = next(t for t in templates if t["name"].endswith("cm.yaml"))["data"]
    assert "{{ .Release.Name }}" in source  # raw template, not rendered


def test_crds_expose_the_crd_objects(extras: helm.Chart) -> None:
    crds = extras.crds
    assert len(crds) == 1
    assert crds[0]["filename"].endswith("widgets.yaml")
    assert "CustomResourceDefinition" in crds[0]["data"]


def test_schema_present_and_absent(extras: helm.Chart, chart: helm.Chart) -> None:
    assert extras.schema is not None
    assert extras.schema.get("type") == "object"
    assert chart.schema is None  # the minimal fixture ships no schema


def test_dependencies_reflect_loaded_subcharts(extras: helm.Chart) -> None:
    # The dependency is declared but not vendored under charts/: it appears
    # in metadata, not in the loaded-subchart list.
    assert extras.dependencies == []
    declared = extras.metadata.get("dependencies") or []
    assert [d["name"] for d in declared] == ["absent"]


def test_load_archive_roundtrip(extras: helm.Chart, tmp_path: Path) -> None:
    archive = Path(extras.save(tmp_path))
    with helm.Chart.load_archive(archive.read_bytes()) as loaded:
        assert loaded.name == "extras"
        assert loaded.version == "1.2.3"


def test_load_archive_rejects_garbage() -> None:
    with pytest.raises(helm.HelmError):
        helm.Chart.load_archive(b"not a chart archive")


def test_save_dir_writes_a_directory(extras: helm.Chart, tmp_path: Path) -> None:
    out = Path(extras.save_dir(tmp_path / "unpacked"))
    assert out.is_dir()
    assert (out / "Chart.yaml").is_file()
    with helm.Chart.load(out) as reloaded:
        assert reloaded.name == "extras"


def test_create_from_starter(tmp_path: Path, chart_dir: Path) -> None:
    with helm.Chart.create_from("fromstarter", tmp_path, chart_dir) as created:
        assert created.name == "fromstarter"


def test_expand_unpacks_an_archive(extras: helm.Chart, tmp_path: Path) -> None:
    archive = extras.save(tmp_path)
    dest = tmp_path / "expanded"
    dest.mkdir()
    helm.expand(dest, archive)
    assert (dest / "extras" / "Chart.yaml").is_file()


def test_digest_is_sha256(extras: helm.Chart, tmp_path: Path) -> None:
    archive = extras.save(tmp_path)
    digest = helm.digest(archive)
    assert digest.startswith("sha256:")
    assert digest == helm.digest(archive)  # stable


def test_sign_requires_a_keyring(extras: helm.Chart, tmp_path: Path) -> None:
    archive = extras.save(tmp_path)
    with pytest.raises(helm.HelmError):
        helm.sign(archive, key="nobody", keyring=tmp_path / "missing-keyring.gpg")


def test_values_from_yaml() -> None:
    assert helm.values_from_yaml("a: 1\nb:\n  c: two\n") == {"a": 1, "b": {"c": "two"}}


def test_values_from_yaml_rejects_bad_yaml() -> None:
    with pytest.raises(helm.HelmError):
        helm.values_from_yaml(":\tnot yaml [")


def test_lint_with_options(extras_dir: Path) -> None:
    report = helm.lint(extras_dir, strict=True, with_subcharts=True)
    assert report["total_charts_linted"] == 1


def test_lint_rejects_unknown_kube_version(extras_dir: Path) -> None:
    with pytest.raises(helm.HelmError):
        helm.lint(extras_dir, kube_version="not-a-version")


def test_dependency_list_reports_missing(extras_dir: Path) -> None:
    deps = helm.dependency_list(extras_dir)
    assert deps == [
        {
            "name": "absent",
            "version": "9.9.9",
            "repository": "https://charts.invalid",
            "status": "missing",
        }
    ]
