"""helm-python — the Helm v4 SDK for Python.

Binds to ``libhelm_c`` (the C ABI over Helm's Go SDK) with ctypes, so no Go
toolchain, compiler, or ``helm`` binary is needed at runtime.

    >>> import helm_python as helm
    >>> helm.validate_release_name("my-release")
    >>> helm.parse_set_string("image.tag=v2")
    {'image': {'tag': 'v2'}}
"""

from __future__ import annotations

import json
from typing import Any

from . import _native
from ._handle import NativeHandle
from ._native import (
    EXPECTED_HELM_C_VERSION,
    EXPECTED_HELM_SDK_VERSION,
    helm_c_version,
    helm_sdk_version,
    library_path,
    open_handles_count,
)
from .chart import (
    Chart,
    dependency_list,
    digest,
    expand,
    lint,
    package,
    sign,
    values_from_yaml,
    verify,
)
from .config import Config, HelmContext
from .errors import (
    ErrorCode,
    HelmCancelledError,
    HelmChartInvalidError,
    HelmChartLoadError,
    HelmError,
    HelmInvalidArgError,
    HelmInvalidHandleError,
    HelmIOError,
    HelmKubeError,
    HelmLibraryError,
    HelmNotFoundError,
    HelmPanicError,
    HelmRegistryError,
    HelmReleaseError,
    HelmRenderError,
    HelmRepoError,
    HelmStorageError,
    HelmUnknownError,
    HelmValuesError,
    HelmWrongHandleTypeError,
)
from .logging import disable_logging, enable_logging
from .registry import (
    RegistryClient,
    dependency_build,
    dependency_update,
    pull,
    push,
    repo_index,
    repo_index_generate,
    show,
)

__version__ = "0.2.1"

__all__ = [
    "EXPECTED_HELM_C_VERSION",
    "EXPECTED_HELM_SDK_VERSION",
    "Chart",
    "Config",
    "ErrorCode",
    "HelmCancelledError",
    "HelmChartInvalidError",
    "HelmChartLoadError",
    "HelmContext",
    "HelmError",
    "HelmIOError",
    "HelmInvalidArgError",
    "HelmInvalidHandleError",
    "HelmKubeError",
    "HelmLibraryError",
    "HelmNotFoundError",
    "HelmPanicError",
    "HelmRegistryError",
    "HelmReleaseError",
    "HelmRenderError",
    "HelmRepoError",
    "HelmStorageError",
    "HelmUnknownError",
    "HelmValuesError",
    "HelmWrongHandleTypeError",
    "NativeHandle",
    "RegistryClient",
    "__version__",
    "dependency_build",
    "dependency_list",
    "dependency_update",
    "digest",
    "disable_logging",
    "enable_logging",
    "expand",
    "helm_c_version",
    "helm_sdk_version",
    "library_path",
    "lint",
    "open_handles_count",
    "package",
    "parse_set_file",
    "parse_set_json",
    "parse_set_literal",
    "parse_set_string",
    "parse_set_string_values",
    "pull",
    "push",
    "repo_index",
    "repo_index_generate",
    "show",
    "sign",
    "validate_release_name",
    "values_from_yaml",
    "verify",
]


def validate_release_name(name: str) -> None:
    """Validate a Helm release name (max 53 chars, DNS-label charset).

    Raises:
        HelmInvalidArgError: if the name is not usable as a release name.
    """
    _native.call_status("helm_release_name_validate", name)


def parse_set_string(expression: str) -> dict[str, Any]:
    """Parse a Helm ``--set`` expression into a dictionary.

        >>> parse_set_string("a=1,b.c=two,ports={80,443}")
        {'a': 1, 'b': {'c': 'two'}, 'ports': [80, 443]}

    Raises:
        HelmValuesError: if the expression is malformed.
    """
    parsed: dict[str, Any] = json.loads(_native.call_string("helm_strvals_parse", expression))
    return parsed


def parse_set_string_values(expression: str) -> dict[str, Any]:
    """Parse a ``--set-string`` expression: values stay strings.

    >>> parse_set_string_values("port=80")
    {'port': '80'}
    """
    parsed: dict[str, Any] = json.loads(
        _native.call_string("helm_strvals_parse_string", expression)
    )
    return parsed


def parse_set_json(expression: str) -> dict[str, Any]:
    """Parse a ``--set-json`` expression: each value is a JSON document.

    >>> parse_set_json('a={"b":[1,2]}')
    {'a': {'b': [1, 2]}}
    """
    parsed: dict[str, Any] = json.loads(_native.call_string("helm_strvals_parse_json", expression))
    return parsed


def parse_set_literal(expression: str) -> dict[str, Any]:
    """Parse a ``--set-literal`` expression: the value is taken verbatim.

    >>> parse_set_literal("a=b,c=d")
    {'a': 'b,c=d'}
    """
    parsed: dict[str, Any] = json.loads(
        _native.call_string("helm_strvals_parse_literal", expression)
    )
    return parsed


def parse_set_file(expression: str) -> dict[str, Any]:
    """Parse a ``--set-file`` expression: each value is read from a file path.

    Raises:
        HelmValuesError: if the expression is malformed or a file is
            unreadable.
    """
    parsed: dict[str, Any] = json.loads(_native.call_string("helm_strvals_parse_file", expression))
    return parsed
