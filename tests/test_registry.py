"""Registry, repository, and dependency operations.

HTTP-repository paths run against a real chart repository served from a temp
directory, so no network access is required. OCI paths are exercised through
their error and marshalling paths here; the full OCI round trip is covered in
helm-c-sdk's own suite against an in-process registry.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

import helm_python as helm

from .test_chart import _write_chart

INDEX_TEMPLATE = """apiVersion: v1
entries:
  sample:
    - apiVersion: v2
      name: sample
      version: 0.1.0
      appVersion: "1.0.0"
      description: Generated test chart
      urls:
        - {url}
      digest: {digest}
generated: "2026-01-01T00:00:00Z"
"""


@pytest.fixture(scope="module")
def chart_repo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Serve a one-chart Helm repository over HTTP; yields its base URL."""
    root = tmp_path_factory.mktemp("repo")
    source = tmp_path_factory.mktemp("src")
    chart_dir = _write_chart(source)
    archive = Path(helm.package(chart_dir, destination=root))

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (root / "index.yaml").write_text(INDEX_TEMPLATE.format(url=archive.name, digest=digest))

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --- chart repositories ---------------------------------------------------


def test_repo_index(chart_repo: str) -> None:
    index = helm.repo_index(chart_repo)
    assert index["apiVersion"] == "v1"
    assert "sample" in index["entries"]
    assert index["entries"]["sample"][0]["version"] == "0.1.0"


def test_repo_index_unreachable() -> None:
    with pytest.raises(helm.HelmRepoError):
        helm.repo_index("http://127.0.0.1:1")


def test_pull_from_http_repo(chart_repo: str, tmp_path: Path) -> None:
    result = helm.pull("sample", repo_url=chart_repo, version="0.1.0", destination=tmp_path)
    assert "output" in result

    archive = tmp_path / "sample-0.1.0.tgz"
    assert archive.is_file()
    with helm.Chart.load(archive) as chart:
        assert chart.name == "sample"


def test_pull_untars(chart_repo: str, tmp_path: Path) -> None:
    helm.pull(
        "sample",
        repo_url=chart_repo,
        destination=tmp_path,
        untar=True,
        untar_dir=tmp_path / "unpacked",
    )
    assert (tmp_path / "unpacked" / "sample" / "Chart.yaml").is_file()


def test_pull_missing_chart(chart_repo: str, tmp_path: Path) -> None:
    with pytest.raises(helm.HelmRepoError):
        helm.pull("no-such-chart", repo_url=chart_repo, destination=tmp_path)


# --- dependencies ---------------------------------------------------------


def _write_parent(root: Path, repo_url: str) -> Path:
    parent = root / "parent"
    parent.mkdir()
    (parent / "Chart.yaml").write_text(
        "apiVersion: v2\n"
        "name: parent\n"
        "version: 0.1.0\n"
        "dependencies:\n"
        "  - name: sample\n"
        '    version: "0.1.0"\n'
        f'    repository: "{repo_url}"\n'
    )
    return parent


def test_dependency_update_and_build(chart_repo: str, tmp_path: Path) -> None:
    """Dependencies resolve without any `helm repo add` on the machine."""
    parent = _write_parent(tmp_path, chart_repo)

    helm.dependency_update(parent)
    assert (parent / "charts" / "sample-0.1.0.tgz").is_file()
    assert (parent / "Chart.lock").is_file()

    # Rebuild strictly from the lock file.
    for entry in (parent / "charts").iterdir():
        entry.unlink()
    helm.dependency_build(parent)
    assert (parent / "charts" / "sample-0.1.0.tgz").is_file()


def test_dependency_update_unreachable_repo(tmp_path: Path) -> None:
    parent = _write_parent(tmp_path, "http://127.0.0.1:1")
    with pytest.raises(helm.HelmRepoError):
        helm.dependency_update(parent)


def test_dependency_update_on_chart_without_dependencies(tmp_path: Path) -> None:
    with helm.Chart.create("standalone", tmp_path) as chart:
        assert chart.name == "standalone"
    helm.dependency_update(tmp_path / "standalone")  # must be a no-op, not an error


# --- registry clients -----------------------------------------------------


def test_client_lifecycle() -> None:
    client = helm.RegistryClient()
    assert not client.closed
    client.close()
    assert client.closed
    client.close()  # idempotent


def test_client_context_manager() -> None:
    with helm.RegistryClient(plain_http=True) as client:
        assert not client.closed
    assert client.closed


def test_client_options_accepted(tmp_path: Path) -> None:
    creds = tmp_path / "config.json"
    with helm.RegistryClient(debug=True, plain_http=True, credentials_file=creds) as client:
        assert not client.closed


def test_login_to_unreachable_registry() -> None:
    with helm.RegistryClient(plain_http=True) as client, pytest.raises(helm.HelmRegistryError):
        client.login("127.0.0.1:1", "user", "pass", insecure=True, plain_http=True)


def test_logout_removes_a_stored_credential(tmp_path: Path) -> None:
    """Log out against an isolated store, so the result is the same everywhere.

    A client built without ``credentials_file`` uses whatever backend the
    machine has configured — a plain file on a bare runner, but Docker's
    credential helper on a developer laptop — and those disagree about what
    deleting a missing entry means. Pointing at our own file keeps the test
    deterministic, and lets it assert the credential is really gone rather
    than just that a call did not raise.
    """
    creds = tmp_path / "config.json"
    auth = base64.b64encode(b"user:pass").decode()
    creds.write_text(json.dumps({"auths": {"127.0.0.1:1": {"auth": auth}}}))

    with helm.RegistryClient(credentials_file=creds) as client:
        client.logout("127.0.0.1:1")

    assert "127.0.0.1:1" not in json.loads(creds.read_text()).get("auths", {})


def test_logout_of_an_unknown_host_fails_as_a_typed_error(tmp_path: Path) -> None:
    """Whether a missing entry is an error is the store's business, not ours.

    What this binding guarantees is that if the SDK does report a failure it
    arrives as HelmRegistryError, not a crash or a bare status code.
    """
    creds = tmp_path / "config.json"
    creds.write_text(json.dumps({"auths": {}}))

    with helm.RegistryClient(credentials_file=creds) as client:
        try:
            client.logout("nosuchhost.invalid")
        except helm.HelmRegistryError as exc:
            assert exc.code is not None


def test_push_missing_archive(tmp_path: Path) -> None:
    with helm.RegistryClient(plain_http=True) as client, pytest.raises(helm.HelmError):
        client.push(tmp_path / "nope.tgz", "oci://127.0.0.1:1/charts", plain_http=True)


def test_pull_oci_unreachable(tmp_path: Path) -> None:
    with pytest.raises(helm.HelmError):
        helm.pull(
            "oci://127.0.0.1:1/charts/sample",
            destination=tmp_path,
            plain_http=True,
            version="0.1.0",
        )


def test_closed_client_rejects_use() -> None:
    client = helm.RegistryClient()
    client.close()
    with pytest.raises(helm.HelmError):
        client.logout("example.com")
