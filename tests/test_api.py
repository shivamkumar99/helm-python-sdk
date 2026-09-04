"""The public Phase 0 surface, exercised against the real library."""

from __future__ import annotations

import pytest

import helm_python as helm


def test_validate_release_name_accepts_valid_names() -> None:
    helm.validate_release_name("my-release")
    helm.validate_release_name("release-123")


@pytest.mark.parametrize("name", ["", "MyRelease", "my_release", "a" * 54])
def test_validate_release_name_rejects_invalid_names(name: str) -> None:
    with pytest.raises(helm.HelmInvalidArgError):
        helm.validate_release_name(name)


def test_parse_set_string_scalars_and_nesting() -> None:
    assert helm.parse_set_string("a=1,b=two") == {"a": 1, "b": "two"}
    assert helm.parse_set_string("image.tag=v2") == {"image": {"tag": "v2"}}


def test_parse_set_string_lists() -> None:
    assert helm.parse_set_string("ports={80,443}") == {"ports": [80, 443]}


def test_parse_set_string_rejects_malformed_input() -> None:
    with pytest.raises(helm.HelmValuesError):
        helm.parse_set_string("a=1,,=x=")


def test_unicode_survives_the_boundary() -> None:
    """Strings cross as UTF-8 in both directions."""
    assert helm.parse_set_string("greeting=héllo-世界") == {"greeting": "héllo-世界"}


def test_public_metadata() -> None:
    assert helm.__version__
    assert helm.library_path.is_file()
    assert helm.helm_sdk_version() == helm.EXPECTED_HELM_SDK_VERSION
