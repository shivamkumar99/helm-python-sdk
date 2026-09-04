"""OCI registries, chart repositories, and chart dependencies.

>>> with RegistryClient() as client:
...     client.login("registry.example.com", "user", "token")
...     client.push("./dist/mychart-1.0.0.tgz", "oci://registry.example.com/charts")
"""

from __future__ import annotations

import json
import os
from typing import Any

from . import _native
from ._handle import NativeHandle

__all__ = [
    "RegistryClient",
    "dependency_build",
    "dependency_update",
    "pull",
    "push",
    "repo_index",
    "repo_index_generate",
    "show",
]

StrPath = str | os.PathLike[str]

_NO_CLIENT = 0


def _opts(**pairs: Any) -> str | None:
    """Build an options JSON payload, omitting unset values."""
    present = {key: value for key, value in pairs.items() if value is not None}
    return json.dumps(present) if present else None


def _loads(payload: str) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(payload)
    return decoded


class RegistryClient(NativeHandle):
    """A client for an OCI registry.

    Credentials obtained by :meth:`login` persist in the client's credentials
    file until :meth:`logout`. Passwords are used for the login call only and
    are never logged or echoed back in errors.
    """

    _free_func = "helm_registry_client_free"
    _kind = "registry client"

    def __init__(
        self,
        *,
        debug: bool = False,
        plain_http: bool = False,
        credentials_file: StrPath | None = None,
    ) -> None:
        """Create a registry client.

        Args:
            debug: emit verbose client output through the log handler.
            plain_http: talk HTTP instead of HTTPS (local registries).
            credentials_file: where logins are stored; defaults to Helm's
                own registry configuration.
        """
        options = _opts(
            debug=debug or None,
            plain_http=plain_http or None,
            credentials_file=None if credentials_file is None else os.fspath(credentials_file),
        )
        super().__init__(_native.call_handle("helm_registry_client_new", options))

    def login(
        self,
        host: str,
        username: str,
        password: str,
        *,
        insecure: bool = False,
        plain_http: bool = False,
    ) -> None:
        """Authenticate against ``host`` (e.g. ``"registry.example.com"``).

        Raises:
            HelmRegistryError: on bad credentials or an unreachable host.
        """
        _native.call_status(
            "helm_registry_login",
            self._raw(),
            host,
            username,
            password,
            _opts(insecure=insecure or None, plain_http=plain_http or None),
        )

    def logout(self, host: str) -> None:
        """Remove stored credentials for ``host``."""
        _native.call_status("helm_registry_logout", self._raw(), host)

    def pull(self, chart_ref: str, **kwargs: Any) -> dict[str, Any]:
        """Download a chart using this client. See :func:`pull`."""
        return pull(chart_ref, client=self, **kwargs)

    def push(self, chart_path: StrPath, remote: str, **kwargs: Any) -> dict[str, Any]:
        """Upload a chart archive using this client. See :func:`push`."""
        return push(chart_path, remote, client=self, **kwargs)

    def tags(self, ref: str) -> list[str]:
        """Semver tags of an ``oci://host/path/chart`` reference, newest first.

        The OCI counterpart of reading an HTTP repository index: "which
        versions exist?".
        """
        tags: list[str] = json.loads(_native.call_string("helm_registry_tags", self._raw(), ref))
        return tags

    def resolve(self, ref: str) -> dict[str, Any]:
        """Manifest descriptor of ``oci://host/path/chart:tag``.

        Returns:
            ``{"digest": "sha256:...", "media_type": str, "size": int}``.
        """
        return _loads(_native.call_string("helm_registry_resolve", self._raw(), ref))

    def show(self, chart_ref: str, **kwargs: Any) -> str:
        """Show a chart's definition without installing. See :func:`show`."""
        return show(chart_ref, client=self, **kwargs)


def _client_handle(client: RegistryClient | None) -> object:
    """Resolve an optional client to a handle; 0 means "use a default"."""
    return _native.HANDLE(_NO_CLIENT) if client is None else client._raw()


def pull(
    chart_ref: str,
    *,
    client: RegistryClient | None = None,
    destination: StrPath | None = None,
    version: str | None = None,
    repo_url: str | None = None,
    untar: bool = False,
    untar_dir: StrPath | None = None,
    plain_http: bool = False,
    insecure_skip_tls_verify: bool = False,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    """Download a chart from an HTTP repository or an ``oci://`` reference.

    Two reference styles:

    * HTTP repository — ``chart_ref`` is the chart name and ``repo_url`` the
      repository, e.g. ``pull("mychart", repo_url="https://charts.example.com")``.
    * OCI — ``chart_ref`` is ``"oci://host/path/name"``. Pass a logged-in
      ``client`` for private registries; otherwise a default client is used.

    Returns:
        ``{"output": str}`` — the archive lands in ``destination``
        (default: the current directory) as ``<name>-<version>.tgz``.

    Raises:
        HelmRepoError: if the chart or repository could not be reached.
    """
    return _loads(
        _native.call_string(
            "helm_pull",
            _client_handle(client),
            chart_ref,
            _opts(
                dest_dir=None if destination is None else os.fspath(destination),
                version=version,
                repo_url=repo_url,
                untar=untar or None,
                untar_dir=None if untar_dir is None else os.fspath(untar_dir),
                plain_http=plain_http or None,
                insecure_skip_tls_verify=insecure_skip_tls_verify or None,
                username=username,
                password=password,
            ),
        )
    )


def push(
    chart_path: StrPath,
    remote: str,
    *,
    client: RegistryClient | None = None,
    plain_http: bool = False,
    insecure_skip_tls_verify: bool = False,
) -> dict[str, Any]:
    """Upload a chart ``.tgz`` to an OCI remote.

    ``remote`` is the repository root (``"oci://host/path"``); the chart name
    and version come from the archive itself. Private registries need a
    logged-in ``client``.

    Raises:
        HelmRegistryError: on authentication or transport failures.
    """
    return _loads(
        _native.call_string(
            "helm_push",
            _client_handle(client),
            os.fspath(chart_path),
            remote,
            _opts(
                plain_http=plain_http or None,
                insecure_skip_tls_verify=insecure_skip_tls_verify or None,
            ),
        )
    )


def repo_index(
    repo_url: str,
    *,
    username: str | None = None,
    password: str | None = None,
    insecure_skip_tls_verify: bool = False,
) -> dict[str, Any]:
    """Fetch and parse a chart repository's ``index.yaml``.

    Returns:
        ``{"apiVersion": str, "entries": {name: [versions...]}, ...}``.
        Large repositories produce large results.

    Raises:
        HelmRepoError: if the index could not be fetched or parsed.
    """
    return _loads(
        _native.call_string(
            "helm_repo_index_download",
            repo_url,
            _opts(
                username=username,
                password=password,
                insecure_skip_tls_verify=insecure_skip_tls_verify or None,
            ),
        )
    )


def show(
    chart_ref: str,
    *,
    client: RegistryClient | None = None,
    format: str = "all",
    devel: bool = False,
    version: str | None = None,
    repo_url: str | None = None,
    plain_http: bool = False,
) -> str:
    """``helm show``: a chart's definition, values, README, or CRDs.

    Nothing is installed; remote references are pulled through the same
    private path as :func:`pull`.

    Args:
        chart_ref: a local path, a repo chart name (with ``repo_url``), or an
            ``oci://`` reference.
        client: optional logged-in client for private registries.
        format: ``"all"`` (default), ``"chart"``, ``"values"``, ``"readme"``,
            or ``"crds"``.

    Returns:
        The SDK's text rendering (YAML/Markdown).
    """
    return _native.call_string(
        "helm_show",
        _client_handle(client),
        chart_ref,
        _opts(
            format=format if format != "all" else None,
            devel=devel or None,
            version=version,
            chart_repo_url=repo_url,
            plain_http=plain_http or None,
        ),
    )


def repo_index_generate(
    directory: StrPath,
    *,
    base_url: str | None = None,
    merge: StrPath | None = None,
    json_index: bool = False,
) -> dict[str, Any]:
    """``helm repo index``: index every ``*.tgz`` in ``directory``.

    Writes ``directory/index.yaml`` (and ``index.json`` when ``json_index``).

    Args:
        base_url: absolute URL prefix for the entries.
        merge: an existing ``index.yaml`` whose entries are kept for versions
            ``directory`` no longer holds.

    Returns:
        The generated index as a dictionary.
    """
    return _loads(
        _native.call_string(
            "helm_repo_index_generate",
            os.fspath(directory),
            _opts(
                base_url=base_url,
                merge=None if merge is None else os.fspath(merge),
                json=json_index or None,
            ),
        )
    )


def dependency_update(
    chart_dir: StrPath,
    *,
    skip_refresh: bool = False,
    keyring: StrPath | None = None,
    verify: bool = False,
    plain_http: bool = False,
) -> None:
    """Resolve a chart's dependencies into ``charts/`` and write ``Chart.lock``.

    The repositories named in ``Chart.yaml`` are registered automatically in a
    private temporary configuration, so no ``helm repo add`` is needed and
    your Helm configuration is left untouched.

    Raises:
        HelmRepoError: if a dependency could not be resolved or downloaded.
    """
    _native.call_status(
        "helm_dependency_update",
        os.fspath(chart_dir),
        _opts(
            skip_refresh=skip_refresh or None,
            keyring=None if keyring is None else os.fspath(keyring),
            verify=verify or None,
            plain_http=plain_http or None,
        ),
    )


def dependency_build(
    chart_dir: StrPath,
    *,
    skip_refresh: bool = False,
    keyring: StrPath | None = None,
    verify: bool = False,
    plain_http: bool = False,
) -> None:
    """Rebuild ``charts/`` from an existing ``Chart.lock``.

    Raises:
        HelmRepoError: if the lock could not be satisfied.
    """
    _native.call_status(
        "helm_dependency_build",
        os.fspath(chart_dir),
        _opts(
            skip_refresh=skip_refresh or None,
            keyring=None if keyring is None else os.fspath(keyring),
            verify=verify or None,
            plain_http=plain_http or None,
        ),
    )
