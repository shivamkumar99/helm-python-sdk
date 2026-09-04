# PLAN.md — helm-python-sdk implementation plan

> Phase 0 landed 2026-08-15 (native layer, error mapping, packaging, gates);
> later phases below are the roadmap.
> Binds Python to `libhelm_c` (github.com/shivamkumar99/helm-c-sdk), the C ABI
> over the Helm v4 Go SDK: pure ctypes, CDLL of a packaged library,
> argtypes/restype declaration tables, error-code → exception mapping.

## 1. Goal

`pip install helm-python-sdk` → charts, registries, and the full release lifecycle
from Python, on Linux/macOS/Windows, with no Go toolchain, no compiler, and no
helm binary on the user's machine.

## 2. Mechanism decision — why ctypes (alternatives considered)

| Option | Verdict |
|---|---|
| **ctypes** | **CHOSEN** — stdlib only, no install-time compile, our ABI maps 1:1 (status ints, out-params, JSON strings, uint64 handles; no struct returns). CFUNCTYPE covers the log callback; GIL is acquired automatically for calls from Go threads. |
| cffi (ABI mode) | Strong runner-up: `ffi.cdef` can consume helm_c.h nearly verbatim (less signature-typo risk). Adds a runtime dep. Fallback if the ctypes declaration table proves error-prone. |
| Cython / pybind11 / raw CPython extension | Compile step per platform × Python version (big wheels matrix) for zero benefit here — the work is I/O-bound Helm operations, not marshalling. Rejected. |
| gopy (generate extension from Go directly) | Bypasses helm-c entirely: couples every wheel to a Go build, weaker memory/ownership control, and throws away the hardened, tested ABI. Rejected. |
| subprocess helm CLI | Not a binding; loses structured errors, cancellation, in-process performance. Rejected. |

## 2.1 Safeguards against the classic ctypes-binding pitfalls

ctypes bindings over a C ABI have well-known failure modes; each one is
addressed by design rather than by discipline:

| Classic pitfall | helm-python's answer |
|---|---|
| `argtypes`/`restype` declared ad hoc near call sites, drifting over time | One declaration table in `_native.py`, executed once at import |
| Hand-maintained signatures with no drift check | Table checked (or generated) against `helm_c.h` in CI — signature drift fails the build |
| Struct-by-value returns, awkward and fragile in ctypes | Our ABI has no struct returns at all (status + out-params, designed for FFI) |
| Manual `close()` discipline only — leaks under GC pressure | Context managers + `weakref.finalize` over ABI-guaranteed idempotent frees |
| No leak verification | Leak-gate fixture: `helm_open_handles_count() == 0` per test session |
| Building the native library on the user's machine at install time | Prebuilt wheels bundling checksum-verified, virus-scanned release binaries — `pip install` never compiles |
| Blocking calls only | Optional `asyncio` wrappers (`asyncio.to_thread`) + real cancellation via `HelmContext` (open decision) |

The one genuinely different mechanism worth keeping on the table is **cffi ABI
mode** (declarations parsed from the header itself — eliminates the
signature-drift bug class at the cost of a runtime dependency). Switch trigger:
if the CI header-vs-table check proves fragile or the table becomes a
maintenance burden, move to cffi; the public Python API would not change.

## 3. Package layout (target)

```
helm-python-sdk/   (repo; distribution helm-python-sdk, import helm_python)
  PLAN.md
  pyproject.toml            # hatchling/setuptools; py.typed; platform wheels
  src/helm_python/
    __init__.py             # public exports + version/pin assertions
    _native.py              # CDLL loading + the FULL argtypes/restype table
                            #   (generated/checked against helm_c.h in CI)
    _memory.py              # string_at+free helpers, c_void_p discipline
    errors.py               # HelmError hierarchy from helm_error_code
    chart.py                # Chart (load/create/save/values/metadata/render…)
    config.py               # Config (kube options), HelmContext (cancellation)
    actions.py              # install/upgrade/rollback/uninstall/list/status…
    registry.py             # RegistryClient (login/push/pull), repo index
    logging.py              # helm_set_log_handler → Python logging bridge
    lib/                    # platform library placed here at wheel build
  tests/                    # pytest: unit + integration + leak gate
  .github/workflows/        # ci (3 OS × CPython matrix), wheels+publish
```

## 3.1 Native-library acquisition — three user-facing options (decided)

All three coexist; highest-priority match wins at import time:

| Priority | Option | Trigger | How it works |
|---|---|---|---|
| 1 | **User-supplied library** | `HELM_C_LIB=/path/to/libhelm_c.<ext>` is set | Loader uses that exact file. For users who built helm-c-sdk themselves (`make build` — works on any Go platform), air-gapped hosts, and downgrades/tests. |
| 2 | **Build on the user's system** | `HELM_PYTHON_BUILD=1` at `pip install` time (and automatically when no prebuilt matches the platform) | The sdist build hook first runs a **requirements preflight** — Go ≥ pinned toolchain, a C compiler, `make` — and fails fast with an actionable per-item message if anything is missing. Then it builds from the **vendored helm-c-sdk source snapshot at the pinned tag** (self-contained, checksummed; no unpinned network fetch) and verifies `helm_sdk_version()` before accepting. |
| 3 | **Normal install — prebuilt from GitHub** | default `pip install` | The platform wheel already **bundles** the binary taken from the helm-c-sdk GitHub release (downloaded at wheel-build time in CI, verified against `sha256sums.txt` — the ClamAV-scanned artifacts). User machines get the GitHub-released binary without needing GitHub access or network beyond PyPI. |

Why option 3 bundles at wheel-build time rather than downloading from GitHub
on the user's machine: (a) the repo is currently **private** — end-user
installs would need a GitHub token; (b) install works offline/behind
firewalls that allow only PyPI; (c) the checksum/scan verification happens
once in CI instead of being re-implemented on every user machine. If the repo
goes public, an optional install-time downloader can be added as a variant of
option 2's hook without changing the ladder.

## 3.2 No OS library-path configuration — ever (the path-detection concern)

The classic "library not found" pain (LD_LIBRARY_PATH / DYLD_LIBRARY_PATH /
PATH editing, ldconfig, broken imports after moving a venv) comes from
loading by *name* through the OS loader search path. helm-python avoids the
entire class of problem by construction:

- `_native.py` always calls `ctypes.CDLL(<ABSOLUTE path>)` — resolved at
  import from the package's own location (`Path(__file__).parent / "lib"`),
  then `HELM_C_LIB`. The OS search path is never consulted for our library,
  so nothing needs to be added to it, and venv moves/renames keep working
  because the path is recomputed at each import.
- `libhelm_c` depends only on system libraries (libc/libpthread on Linux,
  System frameworks on macOS, kernel32/ws2_32 etc. on Windows) — no
  transitive private dependencies that would need PATH help. CI asserts this
  with `ldd`/`otool -L`/dumpbin so a future dependency regression is caught.
- Windows-specific: if a transitive DLL ever appears, the fix is
  `os.add_dll_directory(<package lib dir>)` before CDLL — inside the package,
  still zero user configuration.
- Mutating the user's OS environment at install (ldconfig entries, registry
  PATH edits, shell profiles) is explicitly forbidden — installs stay
  contained to the package directory.

At import, whichever library is loaded is validated (`helm_c_version` +
`helm_sdk_version` against the pin) so a stale or mismatched library is a
clear, actionable error instead of undefined behavior.

## 3.3 Is a Python-side build needed? No.

helm-python is **pure Python** (ctypes is stdlib). There is nothing to
compile in the Python layer itself — no C extension, no Cython. "Building the
wheel" is only packaging: placing the correct prebuilt `libhelm_c` next to
the sources and tagging the wheel per platform. The ONLY thing that is ever
compiled is helm-c-sdk's native library, and only in options 1–2 above.

## 4. API sketch (final shape decided in Phase 0)

```python
import helm_python as helm

with helm.Chart.load("./mychart") as chart:
    manifests = chart.render(values={"replicaCount": 3}, name="demo")

with helm.Config(namespace="default") as cfg:  # ~/.kube/config chain
    rel = cfg.install(chart, name="demo", values={"replicaCount": 3}, wait="watcher", timeout=120)
    print(rel["revision"], rel["status"])
    cfg.uninstall("demo")
```
- Cancellation: `helm.HelmContext()` handle passed to install/upgrade; `.cancel()`
  from any thread → `HelmCancelledError`.
- Logging: `helm.enable_logging(level=…)` bridges the C callback into the
  standard `logging` module.

## 5. Phases

### Phase 0 — skeleton & native table — **DONE 2026-08-15**
- [x] `pyproject.toml` (hatchling, py.typed, zero runtime deps, ruff/mypy/pytest config)
- [x] `_native.py`: absolute-path loader (HELM_C_LIB → packaged lib/), the full
      43-symbol declaration table applied once at import, `take_string`
      ownership helper, and `call_status`/`call_string`/`call_handle` helpers
- [x] `errors.py`: `ErrorCode` + exception hierarchy; unmapped codes fall back
      to `HelmUnknownError`; several also subclass ValueError/LookupError/OSError
- [x] `scripts/check_native_table.py`: parses `helm_c.h` and diffs it against
      the table — caught a real canonicalization bug on its first run
- [x] Walking skeleton through the whole stack: `validate_release_name`,
      `parse_set_string`
- [x] Tests (42) incl. per-test + per-session handle leak gates, and a guard
      that no library-returned string is ever typed `c_char_p`
- [x] README, LICENSE/NOTICE, CI (3 OS x CPython 3.10-3.13, builds the pinned
      helm-c-sdk, runs the drift gate, uploads reports)
- Note: `_memory.py` from the sketch was folded into `_native.py` — string
  ownership needs `helm_free_string`, and a separate module would have meant
  a circular import or needless indirection.
### Phase 1 — offline chart surface — **DONE 2026-08-15**
- [x] `_handle.py`: `NativeHandle` base — context manager, idempotent
      `close()`, `weakref.finalize` safety net (safe because ABI frees are
      idempotent), closed-object guard
- [x] `Chart`: `load`, `create`, `metadata`/`name`/`version`/`values`,
      `merge_values`, `validate_schema`, `render`, `save`
- [x] Module helpers: `lint` (findings as data), `package`, `verify`
- [x] 68 tests: lifecycle (context manager, double close, use-after-close,
      GC-frees-handle), rendering with options, schema pass/fail, packaging,
      and provenance verification against generated signing material
### Phase 2 — distribution — **DONE 2026-08-15**
- [x] `RegistryClient` (constructor takes debug/plain_http/credentials_file;
      login/logout/push/pull; context manager like every handle type)
- [x] Module `pull` (HTTP repo via repo_url, or oci:// with an optional
      client), `push`, `repo_index`, `dependency_update`, `dependency_build`
- [x] 84 tests total: HTTP-repository paths run against a real chart repo
      served from a temp dir (index download, pull, untar, dependency
      resolve + rebuild-from-lock) — no network needed; OCI paths covered
      via error/marshalling paths, with the full round trip living in
      helm-c-sdk's Go suite against an in-process registry
### Phase 3 — cluster actions — **DONE 2026-08-15**
- [x] `Config`: the full kube surface (kubeconfig path or inline content,
      context, bearer token, apiserver/CA/TLS-server-name/insecure,
      impersonation user+groups, burst/qps, namespace, storage driver);
      creation is lazy, so connection errors surface on the first action
- [x] `HelmContext`: cancellation from any thread; a cancelled context makes
      install/upgrade raise `HelmCancelledError`
- [x] Actions as `Config` methods: `install`, `upgrade`, `uninstall`,
      `rollback`, `list`, `status`, `history`, `get_values`, `get_metadata`.
      Charts may be a loaded `Chart` **or** a reference (local path, repo
      name + `chart_repo_url`, or `oci://`)
- [x] 99 tests + 5 cluster tests that self-skip without a cluster; a new CI
      job runs them against kind so they cannot silently never run
- Note: `actions.py` from the sketch was folded into `config.py` — every
  action needs the config handle, and splitting them would have separated
  methods from the object they belong to. Module-level `Release`/
  `ReleaseList` aliases exist because `Config.list` shadows the builtin
  ``list`` inside the class body.
### Phase 4 — logging + packaging — **DONE 2026-08-15**
- [x] `logging.py`: `enable_logging(level, logger)` / `disable_logging()`
      bridging the C callback into Python logging on the
      ``helm_python.native`` logger. The callback object is kept referenced
      while installed (collecting it would leave the library calling freed
      memory), dispatch never raises back into C, and a NULL function
      pointer — not `None` — is used to uninstall.
- [x] `scripts/fetch_native_lib.py`: places the library into the package,
      either from a local build (`--from-dir`) or from a helm-c-sdk release
      (`--release`), verifying the archive against `sha256sums.txt` before
      unpacking.
- [x] `scripts/tag_wheel.py`: retags the wheel for its platform. The build
      backend emits `py3-none-any` even with `pure-python = false`, and
      publishing that would let pip install a macOS dylib on Linux.
- [x] `wheels.yml`: builds wheels for linux/macOS(arm+intel)/windows, each
      bundling the verified release binary, smoke-tests every wheel in a
      clean venv, builds the sdist fallback, and publishes to PyPI on tag
      push via trusted publishing.
- [x] Verified locally end to end: built the wheel, installed it into a
      fresh virtualenv, and ran chart create/render from an unrelated
      directory — the library loaded from inside site-packages with no
      environment variables and zero leaked handles.

### Remaining before a public release
- [x] PyPI distribution name: **`helm-python-sdk`**. Checked 2026-08-15 —
      `helm-python` is already taken on PyPI; `helm-python-sdk` is free and
      matches both this repository and its helm-c-sdk sibling. The import
      name stays `helm_python`.
- [ ] Widen helm-c-sdk's release matrix (linux-arm64, darwin-amd64,
      musllinux) so fewer users fall back to building from source.
- [x] **DONE:** the `HELM_PYTHON_BUILD=1` build hook (`hatch_build.py`) with a
      prerequisite preflight (Go with the version from go.mod, a C compiler,
      make) that names what is missing; `scripts/vendor_helm_c.py` vendors
      the pinned source into the sdist (512 KB, 47 Go files) so nothing
      unpinned is fetched at install time. Verified by installing the sdist
      into a clean virtualenv with `HELM_PYTHON_BUILD=1`: it compiled the
      library and rendered a chart. CI verifies the same path so the
      fallback cannot rot unnoticed.
- [ ] Optional: `asyncio` wrappers over the blocking calls.

## 6. Testing

Unit (marshalling, exception map, loader fallbacks) → integration against the
real library (offline chart ops; memory-driver configs; unreachable-cluster
error paths) → leak gate (`helm_open_handles_count() == 0` per session) →
kind e2e in CI. 3 OS × supported CPython versions.

## 7. Open decisions (Phase 0)

1. ~~Package/distribution name on PyPI~~ — **RESOLVED 2026-08-15:**
   `helm-python` is taken, so the distribution is **`helm-python-sdk`**
   (import `helm_python`).
2. Async story: expose blocking calls only, or add `asyncio` wrappers
   (`asyncio.to_thread`) for install/upgrade/pull?
3. Minimum CPython version (3.10? 3.11?) and PyPy support claim.
4. Whether `_native.py`'s table is hand-written + CI-verified, or generated
   from `helm_c.h` by a small parser at build time.
