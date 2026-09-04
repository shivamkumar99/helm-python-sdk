# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-08-20

Upgrades the native layer to helm-c-sdk v0.2.0 (70-symbol ABI; Helm SDK
v4.2.3) and wraps every new capability.

### Added

- **Chart content access** — `Chart.files`, `Chart.templates`, `Chart.crds`,
  `Chart.schema`, `Chart.dependencies`.
- **Chart utilities** — `Chart.load_archive` (bytes, no filesystem),
  `Chart.save_dir`, `Chart.create_from` (starter charts), plus module-level
  `expand`, `digest`, `sign`, `values_from_yaml`, and `dependency_list`.
- **`--set` family** — `parse_set_string_values`, `parse_set_json`,
  `parse_set_literal`, `parse_set_file`.
- **Distribution** — `show` (chart definition/values/README/CRDs without
  installing), `repo_index_generate` (`helm repo index`), and
  `RegistryClient.tags` / `RegistryClient.resolve` OCI queries.
- **Cluster** — `Config.get_all` (`helm get all`), `Config.test`
  (`helm test`), `Config.render` (cluster-aware `lookup`),
  `Config.check_reachable`, and `Config.set_registry_client` for
  `oci://` references through a logged-in client.
- `lint` gained the full `helm lint` option set (`strict`, `namespace`,
  `with_subcharts`, `quiet`, `skip_schema_validation`, `kube_version`).

### Changed

- The bundled native library is helm-c-sdk v0.2.0; wheels embed its
  release binaries.

## [0.1.0] - 2026-08-15

First release. Binds Python to the Helm v4 SDK through
[helm-c-sdk](https://github.com/shivamkumar99/helm-c-sdk) v0.1.0 (Helm SDK
v4.2.3) using `ctypes`, with no runtime dependencies.

### Added

- **Charts** — `Chart.load`, `Chart.create`, `metadata`, `values`,
  `merge_values`, `validate_schema`, `render`, `save`, plus module-level
  `lint`, `package`, and `verify` (GPG provenance).
- **Values** — `parse_set_string` for Helm `--set` expressions, and
  `validate_release_name`.
- **Distribution** — `RegistryClient` (login, logout, push, pull) for OCI
  registries, `pull` and `repo_index` for HTTP chart repositories, and
  `dependency_update` / `dependency_build` (repositories are registered
  automatically, so no `helm repo add` is needed).
- **Releases** — `Config` with the full Kubernetes connection surface
  (kubeconfig path or inline content, context, bearer token, API server,
  CA/TLS, impersonation, throttling, namespace, storage driver) and the
  actions `install`, `upgrade`, `uninstall`, `rollback`, `list`, `status`,
  `history`, `get_values`, `get_metadata`.
- **Cancellation** — `HelmContext`, cancellable from any thread.
- **Logging** — `enable_logging` / `disable_logging`, routing the native
  library's records to the `helm_python.native` logger.
- **Errors** — a typed hierarchy rooted at `HelmError`, mapped from the C
  ABI's stable error codes; common cases also subclass `ValueError`,
  `LookupError`, and `OSError`.
- **Typing** — full annotations with a `py.typed` marker.

### Packaging

- Platform wheels bundle the native library, so `pip install` compiles
  nothing and needs no network beyond PyPI.
- `HELM_PYTHON_BUILD=1` builds the library from the vendored, pinned
  helm-c-sdk source when no wheel matches the platform, after checking for
  Go, a C compiler, and `make`.
- `HELM_C_LIB` points the loader at a library you built yourself.
- The library is loaded by absolute path, so no `LD_LIBRARY_PATH`,
  `DYLD_LIBRARY_PATH`, or `PATH` configuration is ever required.

[0.2.0]: https://github.com/shivamkumar99/helm-python-sdk/releases/tag/v0.2.0
[0.1.0]: https://github.com/shivamkumar99/helm-python-sdk/releases/tag/v0.1.0
