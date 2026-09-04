"""Charts: loading, inspection, values, rendering, and packaging.

Everything here works offline — no cluster and no network are involved.

    >>> with Chart.load("./mychart") as chart:
    ...     chart.metadata["name"]
    ...     manifests = chart.render(values={"replicaCount": 3}, name="demo")
"""

from __future__ import annotations

import ctypes
import json
import os
from typing import Any

from . import _native
from ._handle import NativeHandle

__all__ = [
    "Chart",
    "dependency_list",
    "digest",
    "expand",
    "lint",
    "package",
    "sign",
    "values_from_yaml",
    "verify",
]

StrPath = str | os.PathLike[str]


def _dumps(values: dict[str, Any] | None) -> str | None:
    """Serialize optional values; ``None`` becomes a NULL argument."""
    return None if values is None else json.dumps(values)


def _loads(payload: str) -> dict[str, Any]:
    """Decode a JSON object the library produced."""
    decoded: dict[str, Any] = json.loads(payload)
    return decoded


class Chart(NativeHandle):
    """A loaded Helm chart.

    Charts are immutable and safe to share between threads. Release with
    ``close()`` or by using the instance as a context manager.
    """

    _free_func = "helm_chart_free"
    _kind = "chart"

    @classmethod
    def load(cls, path: StrPath) -> Chart:
        """Load a chart from a directory or ``.tgz`` archive.

        Raises:
            HelmChartLoadError: if the path is not a readable chart.
        """
        return cls(_native.call_handle("helm_chart_load", os.fspath(path)))

    @classmethod
    def load_archive(cls, data: bytes) -> Chart:
        """Load a chart from ``.tgz`` archive bytes held in memory.

        No filesystem round trip: ``data`` is borrowed for the call and
        copied by the library.

        Raises:
            HelmInvalidArgError: if ``data`` is empty or oversized.
            HelmChartLoadError: if the bytes are not a valid chart archive.
        """
        buffer = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
        return cls(_native.call_handle("helm_chart_load_archive", buffer, len(data)))

    @classmethod
    def create(cls, name: str, directory: StrPath) -> Chart:
        """Scaffold a new chart named ``name`` inside ``directory``.

        Returns the newly created chart, already loaded.

        Raises:
            HelmInvalidArgError: if ``name`` is not a valid chart name.
            HelmIOError: if the files could not be written.
        """
        created = _native.call_string("helm_chart_create", name, os.fspath(directory))
        return cls.load(created)

    @classmethod
    def create_from(cls, name: str, directory: StrPath, starter: StrPath) -> Chart:
        """Scaffold a chart from a starter chart directory (``helm create -p``).

        Returns the newly created chart, already loaded.

        Raises:
            HelmInvalidArgError: if ``name`` is not a valid chart name.
            HelmIOError: if the starter is unreadable or files could not be
                written.
        """
        created = _native.call_string(
            "helm_chart_create_from", name, os.fspath(directory), os.fspath(starter)
        )
        return cls.load(created)

    @property
    def metadata(self) -> dict[str, Any]:
        """The chart's ``Chart.yaml`` as a dictionary."""
        return _loads(_native.call_string("helm_chart_metadata", self._raw()))

    @property
    def name(self) -> str:
        """The chart name from its metadata."""
        name = self.metadata.get("name")
        return str(name) if name is not None else ""

    @property
    def version(self) -> str:
        """The chart version from its metadata."""
        version = self.metadata.get("version")
        return str(version) if version is not None else ""

    @property
    def values(self) -> dict[str, Any]:
        """The chart's default values."""
        return _loads(_native.call_string("helm_chart_values", self._raw()))

    @property
    def files(self) -> list[dict[str, str]]:
        """Non-template files (README, LICENSE, …) as ``[{"name", "data"}]``."""
        files: list[dict[str, str]] = json.loads(
            _native.call_string("helm_chart_files", self._raw())
        )
        return files

    @property
    def templates(self) -> list[dict[str, str]]:
        """Raw template sources as ``[{"name", "data"}]`` (not rendered)."""
        templates: list[dict[str, str]] = json.loads(
            _native.call_string("helm_chart_templates", self._raw())
        )
        return templates

    @property
    def crds(self) -> list[dict[str, str]]:
        """CRD objects under ``crds/`` (chart + subcharts) as
        ``[{"name", "filename", "data"}]``."""
        crds: list[dict[str, str]] = json.loads(_native.call_string("helm_chart_crds", self._raw()))
        return crds

    @property
    def schema(self) -> dict[str, Any] | None:
        """The chart's ``values.schema.json``, or ``None`` when it ships none."""
        schema: dict[str, Any] | None = json.loads(
            _native.call_string("helm_chart_schema", self._raw())
        )
        return schema

    @property
    def dependencies(self) -> list[dict[str, Any]]:
        """Metadata of the subcharts actually loaded from ``charts/``.

        Declared-but-absent dependencies appear only in :attr:`metadata`.
        """
        deps: list[dict[str, Any]] = json.loads(
            _native.call_string("helm_chart_dependencies", self._raw())
        )
        return deps

    def merge_values(self, values: dict[str, Any] | None = None) -> dict[str, Any]:
        """Coalesce the chart's defaults with ``values`` (overrides win).

        This is the same composition an install performs, so it is the
        reliable way to preview what a release would actually use.
        """
        merged = _native.call_string("helm_chart_merge_values", self._raw(), _dumps(values))
        return _loads(merged)

    def validate_schema(self, values: dict[str, Any] | None = None) -> None:
        """Validate values against the chart's ``values.schema.json``.

        Charts without a schema always pass.

        Raises:
            HelmValuesError: if validation fails; the message names the
                offending key and constraint.
        """
        _native.call_status("helm_schema_validate", self._raw(), _dumps(values))

    def render(
        self,
        values: dict[str, Any] | None = None,
        *,
        name: str | None = None,
        namespace: str | None = None,
        revision: int | None = None,
        is_install: bool | None = None,
        is_upgrade: bool | None = None,
    ) -> dict[str, str]:
        """Render the chart's templates offline.

        No cluster is contacted; the ``lookup`` template function returns
        empty results.

        Returns:
            A mapping of template path to rendered manifest.

        Raises:
            HelmValuesError: if the values are malformed.
            HelmRenderError: if a template fails to render.
        """
        opts: dict[str, Any] = {}
        if name is not None:
            opts["name"] = name
        if namespace is not None:
            opts["namespace"] = namespace
        if revision is not None:
            opts["revision"] = revision
        if is_install is not None:
            opts["is_install"] = is_install
        if is_upgrade is not None:
            opts["is_upgrade"] = is_upgrade

        rendered = _native.call_string(
            "helm_render",
            self._raw(),
            _dumps(values),
            json.dumps(opts) if opts else None,
        )
        manifests: dict[str, str] = json.loads(rendered)
        return manifests

    def save(self, destination: StrPath) -> str:
        """Archive the chart into ``destination``; returns the ``.tgz`` path."""
        return _native.call_string("helm_chart_save", self._raw(), os.fspath(destination))

    def save_dir(self, destination: StrPath) -> str:
        """Write the chart back as a directory under ``destination``.

        Returns the created chart directory path.
        """
        return _native.call_string("helm_chart_save_dir", self._raw(), os.fspath(destination))


def lint(
    path: StrPath,
    values: dict[str, Any] | None = None,
    *,
    strict: bool | None = None,
    namespace: str | None = None,
    with_subcharts: bool | None = None,
    quiet: bool | None = None,
    skip_schema_validation: bool | None = None,
    kube_version: str | None = None,
) -> dict[str, Any]:
    """Lint the chart at ``path``.

    Lint findings are *data*, not errors: a chart with problems still returns
    a report. Only malformed input raises. The keyword options mirror
    ``helm lint`` (``strict`` treats warnings as errors, ``kube_version``
    e.g. ``"v1.30.0"``).

    Returns:
        ``{"total_charts_linted": int, "messages": [{"severity", "path",
        "error"}], "errors": [str]}``. Severity is 0=unknown, 1=info,
        2=warning, 3=error.
    """
    opts: dict[str, Any] = {}
    if strict is not None:
        opts["strict"] = strict
    if namespace is not None:
        opts["namespace"] = namespace
    if with_subcharts is not None:
        opts["with_subcharts"] = with_subcharts
    if quiet is not None:
        opts["quiet"] = quiet
    if skip_schema_validation is not None:
        opts["skip_schema_validation"] = skip_schema_validation
    if kube_version is not None:
        opts["kube_version"] = kube_version

    if opts:
        report = _native.call_string(
            "helm_lint_run_opts", os.fspath(path), _dumps(values), json.dumps(opts)
        )
    else:
        report = _native.call_string("helm_lint_run", os.fspath(path), _dumps(values))
    return _loads(report)


def expand(destination: StrPath, archive: StrPath) -> None:
    """Unpack a local ``.tgz`` chart archive into ``destination/<chart name>/``."""
    _native.call_status("helm_chart_expand", os.fspath(destination), os.fspath(archive))


def digest(archive: StrPath) -> str:
    """The ``sha256:<hex>`` digest of a chart archive.

    This is the digest repository indexes carry per entry, so a downloaded
    archive can be checked against its index.
    """
    return _native.call_string("helm_chart_digest", os.fspath(archive))


def sign(
    archive: StrPath,
    *,
    key: str,
    keyring: StrPath,
    passphrase_file: StrPath | None = None,
) -> str:
    """Clear-sign a packaged chart; returns the written ``.prov`` path.

    Args:
        archive: the ``.tgz`` to sign.
        key: identity of the signing key in the keyring (unambiguous
            substring match).
        keyring: a PGP **secret** keyring file.
        passphrase_file: file whose first line unlocks a protected key.
            A protected key without it fails — the library never prompts.

    Raises:
        HelmChartInvalidError: unknown key, locked key, or a bad archive.
    """
    opts: dict[str, Any] = {"key": key, "keyring": os.fspath(keyring)}
    if passphrase_file is not None:
        opts["passphrase_file"] = os.fspath(passphrase_file)
    return _native.call_string("helm_chart_sign", os.fspath(archive), json.dumps(opts))


def values_from_yaml(yaml: str) -> dict[str, Any]:
    """Parse a YAML values document (the ``-f``/``--values`` input) to a dict.

    Raises:
        HelmValuesError: if the document is not valid YAML.
    """
    return _loads(_native.call_string("helm_values_from_yaml", yaml))


def dependency_list(chart_dir: StrPath) -> list[dict[str, Any]]:
    """Every dependency declared in ``Chart.yaml`` with its status.

    Returns:
        ``[{"name", "version", "repository", "status"}]`` where status is
        one of ``"ok"``, ``"missing"``, ``"unpacked"``, ``"wrong version"``,
        ``"invalid version"``, ``"corrupt"``, ``"misnamed"``,
        ``"too many matches"``.
    """
    deps: list[dict[str, Any]] = json.loads(
        _native.call_string("helm_dependency_list", os.fspath(chart_dir))
    )
    return deps


def package(
    path: StrPath,
    *,
    destination: StrPath | None = None,
    version: str | None = None,
    app_version: str | None = None,
) -> str:
    """Package the chart at ``path`` into a ``.tgz``; returns the archive path."""
    opts: dict[str, Any] = {}
    if destination is not None:
        opts["destination"] = os.fspath(destination)
    if version is not None:
        opts["version"] = version
    if app_version is not None:
        opts["app_version"] = app_version

    return _native.call_string(
        "helm_package_run", os.fspath(path), json.dumps(opts) if opts else None
    )


def verify(
    path: StrPath, keyring: StrPath, *, provenance_file: StrPath | None = None
) -> dict[str, Any]:
    """Verify a chart archive against its provenance signature.

    Args:
        path: the ``.tgz`` archive.
        keyring: a GPG **public** keyring file.
        provenance_file: defaults to ``<path>.prov``.

    Returns:
        ``{"file_name": str, "file_hash": str, "signed_by": [str]}``.

    Raises:
        HelmChartInvalidError: if the signature is missing or invalid.
    """
    result = _native.call_string(
        "helm_chart_verify",
        os.fspath(path),
        None if provenance_file is None else os.fspath(provenance_file),
        os.fspath(keyring),
    )
    return _loads(result)
