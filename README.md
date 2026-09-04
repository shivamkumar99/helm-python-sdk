# helm-python-sdk — Helm v4 SDK for Python

[![CI](https://github.com/shivamkumar99/helm-python-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/shivamkumar99/helm-python-sdk/actions/workflows/ci.yml)
[![Wheels](https://github.com/shivamkumar99/helm-python-sdk/actions/workflows/wheels.yml/badge.svg)](https://github.com/shivamkumar99/helm-python-sdk/actions/workflows/wheels.yml)
[![License: Apache-2.0](https://img.shields.io/github/license/shivamkumar99/helm-python-sdk)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![helm-c-sdk](https://img.shields.io/badge/helm--c--sdk-v0.2.0-0F1689?logo=helm)](https://github.com/shivamkumar99/helm-c-sdk/releases/tag/v0.2.0)
[![Helm SDK](https://img.shields.io/badge/Helm%20SDK-v4.2.3-0F1689?logo=helm)](https://github.com/helm/helm)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20macOS%20%7C%20Windows-informational)](README.md#install)
[![Zero runtime deps](https://img.shields.io/badge/runtime%20deps-none%20(stdlib%20ctypes)-success)](pyproject.toml)

Use [Helm](https://helm.sh) from Python: load and render charts, talk to OCI registries,
and install/upgrade/roll back releases — **without** the `helm` binary, a Go toolchain, or a
compiler.

It binds to [`libhelm_c`](https://github.com/shivamkumar99/helm-c-sdk) (a C ABI over Helm's
official Go SDK) using `ctypes` from the standard library, so the package itself has **zero
runtime dependencies**.

> **Status: early development, feature-complete API.** Charts, distribution, the release
> lifecycle, logging, and platform wheels all work. See `PLAN.md` for what remains before a
> public release.

## Install

```bash
pip install helm-python-sdk
```

The import name is `helm_python`.

The wheel bundles the native library for your platform, so nothing is compiled at install
time and no environment variables need to be set.

### If no wheel matches your platform

Three options, resolved in this order:

1. **Point at your own build** — build [helm-c-sdk](https://github.com/shivamkumar99/helm-c-sdk)
   (`make build`, works anywhere Go runs) and set:

   ```bash
   export HELM_C_LIB=/path/to/libhelm_c.so     # or .dylib / .dll, or its directory
   ```

2. **Build during install** — requires Go and a C compiler:

   ```bash
   HELM_PYTHON_BUILD=1 pip install --no-binary helm-python-sdk helm-python-sdk
   ```

   The source distribution vendors the pinned helm-c-sdk source, so nothing unpinned is
   fetched. The installer checks for Go, a C compiler, and `make` first and names exactly
   what is missing rather than failing with a compiler error.
3. **Prebuilt wheel** — the default when your platform is in the release matrix.

## Usage

```python
import helm_python as helm

with helm.Chart.load("./mychart") as chart:
    chart.name, chart.version  # 'mychart', '0.1.0'
    chart.values  # default values as a dict
    chart.merge_values({"replicaCount": 3})  # what an install would really use

    manifests = chart.render({"replicaCount": 3}, name="demo", namespace="prod")
    print(manifests["mychart/templates/deployment.yaml"])

    chart.validate_schema({"replicaCount": 3})  # against values.schema.json, if present
    chart.save("./dist")  # -> ./dist/mychart-0.1.0.tgz
```

Charts are handles into the native library. Use them as context managers (above) or call
`close()`; a forgotten chart is still released when it is garbage collected, and closing
twice is safe.

Module-level chart helpers:

```python
helm.lint("./mychart")  # findings are data, not exceptions
helm.package("./mychart", destination="./dist", version="1.2.3")
helm.verify("./dist/mychart-1.2.3.tgz", keyring="~/.gnupg/pubring.gpg")

helm.validate_release_name("my-release")  # raises HelmInvalidArgError if unusable
helm.parse_set_string("image.tag=v2,ports={80,443}")
# {'image': {'tag': 'v2'}, 'ports': [80, 443]}

print(helm.helm_c_version(), helm.helm_sdk_version())  # 0.2.0 v4.2.3
```

Registries, repositories, and dependencies:

```python
# HTTP chart repositories
helm.repo_index("https://charts.example.com")
helm.pull("mychart", repo_url="https://charts.example.com", destination="./dist")

# OCI registries
with helm.RegistryClient() as client:
    client.login("registry.example.com", "user", "token")
    client.push("./dist/mychart-1.0.0.tgz", "oci://registry.example.com/charts")
    client.pull("oci://registry.example.com/charts/mychart", destination="./dist")

# Dependencies — no `helm repo add` needed; your Helm config is untouched
helm.dependency_update("./mychart")
helm.dependency_build("./mychart")
```

Releases:

```python
with helm.Config(namespace="default") as cfg:  # ~/.kube/config, or in-cluster
    release = cfg.install("./mychart", "demo", {"replicaCount": 3}, wait="watcher", timeout=120)
    print(release["revision"], release["status"])  # 1 deployed

    cfg.upgrade("./mychart", "demo", {"replicaCount": 5})
    cfg.history("demo")  # every revision
    cfg.get_values("demo")  # {'replicaCount': 5}
    cfg.rollback("demo", version=1)
    cfg.uninstall("demo")

    for item in cfg.list():
        print(item["name"], item["revision"], item["status"])
```

Long operations can be cancelled from another thread:

```python
ctx = helm.HelmContext()
threading.Timer(30, ctx.cancel).start()
try:
    cfg.install(chart, "demo", context=ctx, wait="watcher", timeout=300)
except helm.HelmCancelledError:
    ...
```

`Config` accepts the whole Kubernetes connection surface — `kubeconfig_path` or inline
`kubeconfig_content`, `kube_context`, bearer `kube_token`, `kube_apiserver`, CA/TLS
settings, impersonation, throttling, `namespace`, and `storage_driver` (`secret`,
`configmap`, `memory`, `sql`).

Errors are a typed hierarchy rooted at `HelmError`, mapped from the ABI's error codes, and
several also subclass familiar builtins so existing `except` clauses keep working:

```python
try:
    helm.parse_set_string("a=1,,=x=")
except helm.HelmValuesError as exc:  # also a ValueError
    print(exc.code, exc.detail)
```

## Logging

The library is silent until you ask for output:

```python
import logging, helm_python as helm

logging.basicConfig(level=logging.INFO)
helm.enable_logging(logging.INFO)  # call before creating a Config
...
helm.disable_logging()
```

Records arrive on the `helm_python.native` logger, so they filter and route like any other
Python logging. Callbacks arrive on library threads; nothing can propagate back into the
native code, so a broken handler cannot crash the process.

## Why no library-path configuration is needed

The library is always loaded by **absolute path** — from inside the installed package, or
from `HELM_C_LIB` — never by bare name through the OS loader search path. Nothing needs to
be added to `LD_LIBRARY_PATH`, `DYLD_LIBRARY_PATH`, or `PATH`, moving a virtualenv does not
break imports, and installing this package never modifies your system configuration.

## Development

```bash
pip install -e ".[dev]"
python scripts/check_native_table.py ../helm-c/include/helm_c.h   # signature drift gate
pytest                                                            # includes the leak gate
ruff check . && ruff format --check . && mypy
```

Tests locate a sibling `helm-c` checkout's `build/` directory automatically; otherwise set
`HELM_C_LIB`.

## Releasing

Wheels must be built from the source tree, not from the sdist, or the bundled library is
dropped:

```bash
python scripts/fetch_native_lib.py --release v0.2.0   # or --from-dir ../helm-c/build
python -m build --wheel                               # NOT `python -m build`
python scripts/tag_wheel.py dist/*.whl                # refuses a wheel with no library
```

CI does this per platform and smoke-tests every wheel in a clean virtualenv.

## License

Apache-2.0. Copyright 2026 Shivam Kumar.
