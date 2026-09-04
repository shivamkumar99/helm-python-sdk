"""Error-code to exception mapping."""

from __future__ import annotations

import pytest

from helm_python import errors


def test_ok_code_does_not_raise() -> None:
    errors.raise_for_code(errors.ErrorCode.OK, None)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (errors.ErrorCode.INVALID_ARG, errors.HelmInvalidArgError),
        (errors.ErrorCode.INVALID_HANDLE, errors.HelmInvalidHandleError),
        (errors.ErrorCode.WRONG_HANDLE_TYPE, errors.HelmWrongHandleTypeError),
        (errors.ErrorCode.PANIC, errors.HelmPanicError),
        (errors.ErrorCode.CANCELLED, errors.HelmCancelledError),
        (errors.ErrorCode.NOT_FOUND, errors.HelmNotFoundError),
        (errors.ErrorCode.IO, errors.HelmIOError),
        (errors.ErrorCode.CHART_LOAD, errors.HelmChartLoadError),
        (errors.ErrorCode.CHART_INVALID, errors.HelmChartInvalidError),
        (errors.ErrorCode.VALUES, errors.HelmValuesError),
        (errors.ErrorCode.RENDER, errors.HelmRenderError),
        (errors.ErrorCode.REGISTRY, errors.HelmRegistryError),
        (errors.ErrorCode.REPO, errors.HelmRepoError),
        (errors.ErrorCode.KUBE, errors.HelmKubeError),
        (errors.ErrorCode.STORAGE, errors.HelmStorageError),
        (errors.ErrorCode.RELEASE, errors.HelmReleaseError),
    ],
)
def test_each_code_maps_to_its_exception(code: int, expected: type[Exception]) -> None:
    with pytest.raises(expected) as excinfo:
        errors.raise_for_code(code, "detail text")
    assert excinfo.value.code == code
    assert "detail text" in str(excinfo.value)


def test_unknown_code_falls_back() -> None:
    """A library newer than this binding must still raise something sane."""
    with pytest.raises(errors.HelmUnknownError):
        errors.raise_for_code(-9999, None)


def test_missing_detail_still_has_a_message() -> None:
    with pytest.raises(errors.HelmNotFoundError) as excinfo:
        errors.raise_for_code(errors.ErrorCode.NOT_FOUND, None)
    assert "-7" in str(excinfo.value)


def test_every_exception_is_a_helm_error() -> None:
    for exc_type in errors._BY_CODE.values():
        assert issubclass(exc_type, errors.HelmError)


def test_selected_exceptions_are_also_builtins() -> None:
    """Ergonomics: callers can catch familiar builtin types."""
    assert issubclass(errors.HelmInvalidArgError, ValueError)
    assert issubclass(errors.HelmNotFoundError, LookupError)
    assert issubclass(errors.HelmIOError, OSError)
