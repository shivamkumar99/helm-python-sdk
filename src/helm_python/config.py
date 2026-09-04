"""Cluster configuration, cancellation, and the release lifecycle.

>>> with Config(namespace="default") as cfg:          # ~/.kube/config
...     release = cfg.install("./mychart", "demo", {"replicaCount": 3})
...     cfg.uninstall("demo")
"""

from __future__ import annotations

import json
import os
from typing import Any

from . import _native
from ._handle import NativeHandle
from .chart import Chart

__all__ = ["Config", "HelmContext", "Release", "ReleaseList"]

StrPath = str | os.PathLike[str]

#: A release summary as returned by the library.
Release = dict[str, Any]
#: Several actions return a list of summaries. Defined at module scope so the
#: annotations below still mean the builtin ``list`` inside ``Config``, whose
#: ``list`` method would otherwise shadow it.
ReleaseList = list[Release]
#: Module-scope alias for the same reason: inside ``Config`` the name ``list``
#: is the method, not the builtin.
_StrList = list[str]

_NONE = 0


def _opts(**pairs: Any) -> str | None:
    """Build an options JSON payload, omitting unset values."""
    present = {key: value for key, value in pairs.items() if value is not None}
    return json.dumps(present) if present else None


def _loads_obj(payload: str) -> Release:
    decoded: Release = json.loads(payload)
    return decoded


def _loads_list(payload: str) -> ReleaseList:
    decoded: ReleaseList = json.loads(payload)
    return decoded


class HelmContext(NativeHandle):
    """A cancellation token for long-running actions.

    Pass it to :meth:`Config.install` or :meth:`Config.upgrade` and call
    :meth:`cancel` from any thread to abort the operation, which then raises
    :class:`~helm_python.HelmCancelledError`.

        >>> ctx = HelmContext()
        >>> threading.Timer(30, ctx.cancel).start()
        >>> cfg.install(chart, "demo", context=ctx)
    """

    _free_func = "helm_context_free"
    _kind = "context"

    def __init__(self) -> None:
        super().__init__(_native.call_handle("helm_context_new"))

    def cancel(self) -> None:
        """Cancel the operation. Safe from any thread and repeatable."""
        _native.call_status("helm_context_cancel", self._raw())


class Config(NativeHandle):
    """A connection to a cluster plus its release storage.

    Creating a config parses its options but does not contact the cluster —
    connection problems surface on the first action.

    **Concurrency:** one config supports actions on *different* releases
    concurrently, but concurrent writes to the *same* release can corrupt its
    history, so serialize per release.
    """

    _free_func = "helm_config_free"
    _kind = "config"

    def __init__(
        self,
        *,
        kubeconfig_path: StrPath | None = None,
        kubeconfig_content: str | None = None,
        kube_context: str | None = None,
        kube_token: str | None = None,
        kube_apiserver: str | None = None,
        kube_ca_file: StrPath | None = None,
        kube_tls_server_name: str | None = None,
        kube_insecure_skip_tls_verify: bool = False,
        kube_as_user: str | None = None,
        kube_as_groups: list[str] | None = None,
        burst_limit: int | None = None,
        qps: float | None = None,
        namespace: str | None = None,
        storage_driver: str | None = None,
    ) -> None:
        """Configure cluster access.

        With neither ``kubeconfig_path`` nor ``kubeconfig_content``, the usual
        resolution applies: ``KUBECONFIG``, then ``~/.kube/config``, then the
        in-cluster service account when running inside a pod.

        Args:
            kubeconfig_path: a kubeconfig file.
            kubeconfig_content: inline kubeconfig YAML, written to a private
                temporary file that is removed when this config is closed.
                Mutually exclusive with ``kubeconfig_path``.
            kube_context: context to select within the kubeconfig.
            kube_token: bearer token authentication.
            kube_apiserver: API server endpoint override.
            kube_ca_file: custom certificate authority.
            kube_tls_server_name: override for server-certificate validation.
            kube_insecure_skip_tls_verify: skip certificate checks.
            kube_as_user, kube_as_groups: impersonation.
            burst_limit, qps: client-side throttling.
            namespace: target namespace (default ``"default"``).
            storage_driver: ``"secret"`` (default), ``"configmap"``,
                ``"memory"``, or ``"sql"``.
        """
        options = _opts(
            kubeconfig_path=None if kubeconfig_path is None else os.fspath(kubeconfig_path),
            kubeconfig_content=kubeconfig_content,
            kube_context=kube_context,
            kube_token=kube_token,
            kube_apiserver=kube_apiserver,
            kube_ca_file=None if kube_ca_file is None else os.fspath(kube_ca_file),
            kube_tls_server_name=kube_tls_server_name,
            kube_insecure_skip_tls_verify=kube_insecure_skip_tls_verify or None,
            kube_as_user=kube_as_user,
            kube_as_groups=kube_as_groups,
            burst_limit=burst_limit,
            qps=qps,
            namespace=namespace,
            storage_driver=storage_driver,
        )
        super().__init__(_native.call_handle("helm_config_new", options))

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _chart_args(chart: Chart | StrPath) -> tuple[object, str | None]:
        """Resolve a chart argument into (handle, reference)."""
        if isinstance(chart, Chart):
            return chart._raw(), None
        return _native.HANDLE(_NONE), os.fspath(chart)

    @staticmethod
    def _context_arg(context: HelmContext | None) -> object:
        return _native.HANDLE(_NONE) if context is None else context._raw()

    # --- write actions ----------------------------------------------------

    def install(
        self,
        chart: Chart | StrPath,
        name: str,
        values: dict[str, Any] | None = None,
        *,
        context: HelmContext | None = None,
        namespace: str | None = None,
        timeout: int | None = None,
        wait: str | None = None,
        dry_run: str | None = None,
        create_namespace: bool = False,
        rollback_on_failure: bool = False,
        description: str | None = None,
        labels: dict[str, str] | None = None,
        chart_repo_url: str | None = None,
        chart_version: str | None = None,
        plain_http: bool = False,
    ) -> Release:
        """Install ``chart`` as release ``name``.

        Args:
            chart: a loaded :class:`~helm_python.Chart`, or a reference — a
                local path, a chart name with ``chart_repo_url``, or an
                ``oci://`` URL.
            name: the release name.
            values: user-supplied values.
            context: a :class:`HelmContext` to allow cancellation.
            timeout: seconds to wait for the operation.
            wait: ``"watcher"``, ``"legacy"``, ``"hookOnly"``, or ``None``.
            dry_run: ``"client"``, ``"server"``, ``"none"``, or ``None``.

        Returns:
            The release summary, including the rendered ``manifest``.

        Raises:
            HelmCancelledError: if ``context`` was cancelled.
            HelmReleaseError: if the install failed.
        """
        handle, ref = self._chart_args(chart)
        payload = _native.call_string(
            "helm_install",
            self._raw(),
            self._context_arg(context),
            handle,
            ref,
            name,
            None if values is None else json.dumps(values),
            _opts(
                namespace=namespace,
                timeout_seconds=timeout,
                wait=wait,
                dry_run=dry_run,
                create_namespace=create_namespace or None,
                rollback_on_failure=rollback_on_failure or None,
                description=description,
                labels=labels,
                chart_repo_url=chart_repo_url,
                chart_version=chart_version,
                plain_http=plain_http or None,
            ),
        )
        return _loads_obj(payload)

    def upgrade(
        self,
        chart: Chart | StrPath,
        name: str,
        values: dict[str, Any] | None = None,
        *,
        context: HelmContext | None = None,
        namespace: str | None = None,
        timeout: int | None = None,
        wait: str | None = None,
        dry_run: str | None = None,
        max_history: int | None = None,
        reset_values: bool = False,
        reuse_values: bool = False,
        cleanup_on_fail: bool = False,
        rollback_on_failure: bool = False,
        description: str | None = None,
        labels: dict[str, str] | None = None,
        chart_repo_url: str | None = None,
        chart_version: str | None = None,
        plain_http: bool = False,
    ) -> Release:
        """Upgrade release ``name`` to ``chart``.

        Accepts the same chart forms as :meth:`install`.

        Returns:
            The release summary for the new revision.

        Raises:
            HelmNotFoundError: if the release does not exist.
            HelmReleaseError: if the upgrade failed.
        """
        handle, ref = self._chart_args(chart)
        payload = _native.call_string(
            "helm_upgrade",
            self._raw(),
            self._context_arg(context),
            handle,
            ref,
            name,
            None if values is None else json.dumps(values),
            _opts(
                namespace=namespace,
                timeout_seconds=timeout,
                wait=wait,
                dry_run=dry_run,
                max_history=max_history,
                reset_values=reset_values or None,
                reuse_values=reuse_values or None,
                cleanup_on_fail=cleanup_on_fail or None,
                rollback_on_failure=rollback_on_failure or None,
                description=description,
                labels=labels,
                chart_repo_url=chart_repo_url,
                chart_version=chart_version,
                plain_http=plain_http or None,
            ),
        )
        return _loads_obj(payload)

    def uninstall(
        self,
        name: str,
        *,
        keep_history: bool = False,
        timeout: int | None = None,
        dry_run: bool = False,
        ignore_not_found: bool = False,
        wait: str | None = None,
        description: str | None = None,
    ) -> Release:
        """Remove release ``name``.

        Returns:
            ``{"info": str, "release": {...}}``.

        Raises:
            HelmNotFoundError: if the release does not exist and
                ``ignore_not_found`` is false.
        """
        payload = _native.call_string(
            "helm_uninstall",
            self._raw(),
            name,
            _opts(
                keep_history=keep_history or None,
                timeout_seconds=timeout,
                dry_run=dry_run or None,
                ignore_not_found=ignore_not_found or None,
                wait=wait,
                description=description,
            ),
        )
        return _loads_obj(payload)

    def rollback(
        self,
        name: str,
        *,
        version: int | None = None,
        timeout: int | None = None,
        wait: str | None = None,
        dry_run: str | None = None,
    ) -> None:
        """Roll release ``name`` back, creating a new revision.

        Args:
            version: the revision to roll back to; ``None`` means the
                previous one.

        Raises:
            HelmNotFoundError: if the release or revision does not exist.
        """
        _native.call_status(
            "helm_rollback",
            self._raw(),
            name,
            _opts(
                version=version,
                timeout_seconds=timeout,
                wait=wait,
                dry_run=dry_run,
            ),
        )

    # --- read actions -----------------------------------------------------

    def list(
        self,
        *,
        all_states: bool = False,
        all_namespaces: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        name_filter: str | None = None,
    ) -> ReleaseList:
        """List releases as summaries (without manifests).

        Args:
            all_states: include every state, not just deployed releases
                (the CLI's ``--all``).
            name_filter: a regular expression matched against release names
                (the CLI's ``--filter``).
        """
        payload = _native.call_string(
            "helm_list",
            self._raw(),
            _opts(
                all=all_states or None,
                all_namespaces=all_namespaces or None,
                limit=limit,
                offset=offset,
                filter=name_filter,
            ),
        )
        return _loads_list(payload)

    def status(self, name: str, *, revision: int | None = None) -> Release:
        """Return the release summary, including its rendered manifest."""
        payload = _native.call_string("helm_status", self._raw(), name, _opts(revision=revision))
        return _loads_obj(payload)

    def history(self, name: str, *, max_revisions: int | None = None) -> ReleaseList:
        """Return the release's revisions, oldest first.

        Args:
            max_revisions: cap on returned revisions (the CLI's ``--max``).
        """
        payload = _native.call_string("helm_history", self._raw(), name, _opts(max=max_revisions))
        return _loads_list(payload)

    def get_values(
        self, name: str, *, all_values: bool = False, revision: int | None = None
    ) -> Release:
        """Return a release's values.

        Args:
            all_values: return the computed values rather than only the
                user-supplied ones (the CLI's ``--all``).
        """
        payload = _native.call_string(
            "helm_get_values",
            self._raw(),
            name,
            _opts(all=all_values or None, revision=revision),
        )
        return _loads_obj(payload)

    def get_metadata(self, name: str, *, revision: int | None = None) -> Release:
        """Return a release's metadata (chart, versions, annotations, ...)."""
        payload = _native.call_string(
            "helm_get_metadata", self._raw(), name, _opts(revision=revision)
        )
        return _loads_obj(payload)

    def get_all(self, name: str, *, revision: int | None = None) -> Release:
        """``helm get all``: the full stored release.

        Returns:
            ``{"summary": {...as status()...}, "hooks": [...], "config":
            {user-supplied values}, "info": {...}}``.
        """
        payload = _native.call_string("helm_get", self._raw(), name, _opts(revision=revision))
        return _loads_obj(payload)

    def test(
        self,
        name: str,
        *,
        timeout: int | None = None,
        logs: bool = False,
        include_names: _StrList | None = None,
        exclude_names: _StrList | None = None,
    ) -> Release:
        """``helm test``: run the release's test hooks.

        Test pods are cleaned up before returning, like the CLI. A failing
        test raises ``HelmReleaseError`` with the SDK's detail.

        Args:
            timeout: seconds to wait for the hooks (``timeout_seconds``).
            logs: collect the test pods' logs into the result.
            include_names / exclude_names: hook name filters.

        Returns:
            ``{"release": {summary}, "logs": "..."}``.
        """
        payload = _native.call_string(
            "helm_test_run",
            self._raw(),
            name,
            _opts(
                timeout_seconds=timeout,
                logs=logs or None,
                include_names=include_names,
                exclude_names=exclude_names,
            ),
        )
        return _loads_obj(payload)

    def check_reachable(self) -> None:
        """Probe the cluster the way every action does first.

        Raises:
            HelmKubeError: when the API server cannot be reached; the
                message carries the SDK's detail.
        """
        _native.call_status("helm_config_check_reachable", self._raw())

    def set_registry_client(self, client: NativeHandle | None) -> None:
        """Bind a logged-in registry client for ``oci://`` chart references.

        ``install``, ``upgrade``, and ``show`` by an ``oci://`` chart_ref then
        use its credentials. Pass ``None`` to unbind. The client must stay
        alive (not closed) while bound.
        """
        handle = _native.HANDLE(_NONE) if client is None else client._raw()
        _native.call_status("helm_config_set_registry_client", self._raw(), handle)

    def render(
        self,
        chart: Chart,
        values: dict[str, Any] | None = None,
        *,
        name: str | None = None,
        namespace: str | None = None,
        revision: int | None = None,
        is_install: bool | None = None,
        is_upgrade: bool | None = None,
    ) -> dict[str, str]:
        """Render a chart cluster-aware: ``lookup`` returns live objects.

        Nothing is created or stored. Only ``lookup`` contacts the API
        server — a chart that never calls it renders even when the cluster
        is unreachable.

        Returns:
            A mapping of template path to rendered manifest.
        """
        opts = _opts(
            name=name,
            namespace=namespace,
            revision=revision,
            is_install=is_install,
            is_upgrade=is_upgrade,
        )
        rendered = _native.call_string(
            "helm_render_with_config",
            self._raw(),
            chart._raw(),
            None if values is None else json.dumps(values),
            opts,
        )
        manifests: dict[str, str] = json.loads(rendered)
        return manifests
